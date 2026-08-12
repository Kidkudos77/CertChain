"""Baseline: Fine-tuned BERT with a linear classification head."""

import torch
import torch.nn as nn
from transformers import BertModel


class BertHeadClassifier(nn.Module):
    """Plain BERT + linear head for classification."""

    def __init__(self, config: dict):
        super().__init__()
        self.num_classes = 3
        bert_name = config.get("bert_model_name", "bert-base-uncased")
        dropout = config.get("cnn", {}).get("dropout", 0.3)

        self.bert = BertModel.from_pretrained(bert_name)
        bert_dim = self.bert.config.hidden_size

        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(bert_dim, self.num_classes)

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        """
        Args:
            input_ids: (batch, seq_len)
            attention_mask: (batch, seq_len)
        Returns:
            logits: (batch, num_classes)
        """
        bert_out = self.bert(input_ids=input_ids, attention_mask=attention_mask)
        # Use [CLS] token representation
        cls_output = bert_out.last_hidden_state[:, 0, :]
        x = self.dropout(cls_output)
        return self.fc(x)
