"""Baseline: CNN text classifier with multi-kernel convolutions."""

import torch
import torch.nn as nn


class CnnClassifier(nn.Module):
    """Multi-kernel CNN for text classification."""

    def __init__(self, config: dict):
        super().__init__()
        self.num_classes = 3
        cnn_cfg = config.get("cnn", {})
        embed_dim = config.get("embed_dim", 300)

        kernel_sizes = cnn_cfg.get("kernel_sizes", [3, 5, 7])
        num_filters = cnn_cfg.get("num_filters", 128)
        dropout = cnn_cfg.get("dropout", 0.3)

        self.convs = nn.ModuleList([
            nn.Sequential(
                nn.Conv1d(embed_dim, num_filters, kernel_size=k, padding=k // 2),
                nn.BatchNorm1d(num_filters),
                nn.ReLU(),
                nn.AdaptiveMaxPool1d(1),
            )
            for k in kernel_sizes
        ])

        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(num_filters * len(kernel_sizes), self.num_classes)

    def forward(self, embeddings: torch.Tensor, **kwargs) -> torch.Tensor:
        """
        Args:
            embeddings: (batch, seq_len, embed_dim)
        Returns:
            logits: (batch, num_classes)
        """
        x = embeddings.permute(0, 2, 1)  # (batch, embed_dim, seq_len)
        conv_outs = [conv(x).squeeze(-1) for conv in self.convs]
        x = torch.cat(conv_outs, dim=1)
        x = self.dropout(x)
        return self.fc(x)
