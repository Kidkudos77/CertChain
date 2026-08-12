"""
Primary Model: BERT + Depth-wise Separable Convolution + Bi-GRU + Softmax

Architecture:
  1. Tokenize sending + receiving course names with BERT tokenizer
  2. Extract BERT embeddings (frozen or fine-tuned per config)
  3. Apply depth-wise separable 1D convolutions (kernel sizes [3, 5, 7])
  4. Feed into 2-layer Bi-GRU
  5. Final hidden states → linear → softmax → 3 classes
"""

import torch
import torch.nn as nn
from transformers import BertModel


class DepthwiseSeparableConv1d(nn.Module):
    """Depth-wise separable convolution: depthwise + pointwise."""

    def __init__(self, in_channels: int, out_channels: int, kernel_size: int, padding: int = 0):
        super().__init__()
        self.depthwise = nn.Conv1d(
            in_channels, in_channels, kernel_size=kernel_size,
            padding=padding, groups=in_channels
        )
        self.pointwise = nn.Conv1d(in_channels, out_channels, kernel_size=1)
        self.bn = nn.BatchNorm1d(out_channels)
        self.relu = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.depthwise(x)
        x = self.pointwise(x)
        x = self.bn(x)
        return self.relu(x)


class BertDscBiGru(nn.Module):
    """BERT + Depth-wise Separable Conv + Bi-GRU classifier."""

    def __init__(self, config: dict):
        super().__init__()
        self.num_classes = 3
        bert_name = config.get("bert_model_name", "bert-base-uncased")
        dsc_cfg = config.get("depthwise_separable_conv", {})
        gru_cfg = config.get("bigru", {})

        # BERT encoder
        self.bert = BertModel.from_pretrained(bert_name)
        bert_dim = self.bert.config.hidden_size  # 768

        # Freeze BERT if config says so
        if not config.get("fine_tune_bert", True):
            for param in self.bert.parameters():
                param.requires_grad = False

        # Depth-wise separable convolutions (multi-kernel)
        kernel_sizes = dsc_cfg.get("kernel_sizes", [3, 5, 7])
        num_filters = dsc_cfg.get("num_filters", 128)

        self.convs = nn.ModuleList([
            DepthwiseSeparableConv1d(
                in_channels=bert_dim,
                out_channels=num_filters,
                kernel_size=k,
                padding=k // 2  # same padding
            )
            for k in kernel_sizes
        ])

        conv_out_dim = num_filters * len(kernel_sizes)

        # Bi-GRU
        hidden_size = gru_cfg.get("hidden_size", 128)
        num_layers = gru_cfg.get("num_layers", 2)
        dropout = gru_cfg.get("dropout", 0.3)

        self.bigru = nn.GRU(
            input_size=conv_out_dim,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            bidirectional=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )

        # Classifier head
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size * 2, self.num_classes)  # *2 for bidirectional

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        """
        Args:
            input_ids: (batch, seq_len)
            attention_mask: (batch, seq_len)
        Returns:
            logits: (batch, num_classes)
        """
        # BERT embeddings: (batch, seq_len, 768)
        bert_out = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        embeddings = bert_out.last_hidden_state

        # Conv expects (batch, channels, seq_len)
        x = embeddings.permute(0, 2, 1)

        # Multi-kernel depth-wise separable conv
        conv_outs = [conv(x) for conv in self.convs]
        # Each is (batch, num_filters, seq_len) — concatenate on channel dim
        x = torch.cat(conv_outs, dim=1)  # (batch, num_filters * n_kernels, seq_len)

        # Back to (batch, seq_len, features) for GRU
        x = x.permute(0, 2, 1)

        # Bi-GRU
        gru_out, _ = self.bigru(x)  # (batch, seq_len, hidden*2)

        # Take the last time step's output
        x = gru_out[:, -1, :]  # (batch, hidden*2)

        # Classify
        x = self.dropout(x)
        logits = self.fc(x)
        return logits
