"""Baseline: CNN + Bidirectional GRU."""

import torch
import torch.nn as nn


class CnnBiGruClassifier(nn.Module):
    """CNN feature extraction followed by Bi-GRU sequence modeling."""

    def __init__(self, config: dict):
        super().__init__()
        self.num_classes = 3
        cnn_cfg = config.get("cnn", {})
        embed_dim = config.get("embed_dim", 300)

        kernel_sizes = cnn_cfg.get("kernel_sizes", [3, 5, 7])
        num_filters = cnn_cfg.get("num_filters", 128)
        dropout = cnn_cfg.get("dropout", 0.3)
        hidden_size = config.get("bigru", {}).get("hidden_size", 128)
        num_layers = config.get("bigru", {}).get("num_layers", 2)

        # CNN layers (preserve sequence)
        self.convs = nn.ModuleList([
            nn.Sequential(
                nn.Conv1d(embed_dim, num_filters, kernel_size=k, padding=k // 2),
                nn.BatchNorm1d(num_filters),
                nn.ReLU(),
            )
            for k in kernel_sizes
        ])

        conv_out_dim = num_filters * len(kernel_sizes)

        # Bi-GRU
        self.bigru = nn.GRU(
            input_size=conv_out_dim,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            bidirectional=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )

        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size * 2, self.num_classes)

    def forward(self, embeddings: torch.Tensor, **kwargs) -> torch.Tensor:
        x = embeddings.permute(0, 2, 1)
        conv_outs = [conv(x) for conv in self.convs]
        x = torch.cat(conv_outs, dim=1)
        x = x.permute(0, 2, 1)

        output, h_n = self.bigru(x)
        # Concatenate final forward and backward hidden states
        x = torch.cat([h_n[-2], h_n[-1]], dim=1)
        x = self.dropout(x)
        return self.fc(x)
