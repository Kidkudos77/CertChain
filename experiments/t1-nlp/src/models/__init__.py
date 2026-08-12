"""Model registry for T1-NLP course equivalency classifier."""

from .bert_dsc_bigru import BertDscBiGru
from .cnn import CnnClassifier
from .lstm import LstmClassifier
from .cnn_bilstm import CnnBiLstmClassifier
from .cnn_bigru import CnnBiGruClassifier
from .bert_head import BertHeadClassifier

MODEL_REGISTRY = {
    "bert_dsc_bigru": BertDscBiGru,
    "cnn": CnnClassifier,
    "lstm": LstmClassifier,
    "cnn_bilstm": CnnBiLstmClassifier,
    "cnn_bigru": CnnBiGruClassifier,
    "bert_head": BertHeadClassifier,
}


def get_model(name: str, config: dict):
    """Instantiate a model by name from the registry."""
    if name not in MODEL_REGISTRY:
        raise ValueError(f"Unknown model: {name}. Available: {list(MODEL_REGISTRY.keys())}")
    return MODEL_REGISTRY[name](config)
