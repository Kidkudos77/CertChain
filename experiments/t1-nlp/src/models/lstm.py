"""Baseline: LSTM text classifier."""

import torch
import torch.nn as nn


class LstmClassifier(nn.Module):
    """Bidirectional LSTM for text classification."""

    def __init__(self, config: dict):
        super().__init__()
        self.num_classes = 3
        embed_dim = config.get("embed_dim", 300)
        hidden_size = config.get("bigru", {}).get("hidden_size", 128)
        num_layers = config.get("bigru", {}).get("num_layers", 2)
        dropout = config.get("bigru", {}).get("dropout", 0.3)

        self.lstm = nn.LSTM(
            input_size=embed_dim,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            bidirectional=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )

        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size * 2, self.num_classes)

    def forward(self, embeddings: torch.Tensor, **kwargs) -> torch.Tensor:
        """
        Args:
            embeddings: (batch, seq_len, embed_dim)
        Returns:
            logits: (batch, num_classes)
        """
        output, (h_n, _) = self.lstm(embeddings)
        # Concatenate final forward and backward hidden states
        x = torch.cat([h_n[-2], h_n[-1]], dim=1)
        x = self.dropout(x)
        return self.fc(x)
