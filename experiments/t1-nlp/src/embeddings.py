"""
Embedding Factory: Word2Vec, GloVe, BERT

Provides a unified interface for loading embeddings. For non-BERT models,
returns an nn.Embedding layer initialized with pre-trained vectors.
For BERT models, the embedding is handled within the model itself.
"""

import logging
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent


def get_embedding_layer(config: dict, vocab: dict[str, int]) -> nn.Embedding | None:
    """
    Factory function that returns an nn.Embedding layer for the specified
    embedding type, or None if BERT (embeddings are internal to the model).

    Args:
        config: Global config dict with 'embedding' key.
        vocab: Token-to-index mapping built from the training data.

    Returns:
        nn.Embedding initialized with pre-trained vectors, or None for BERT.
    """
    embedding_type = config.get("embedding", "bert")

    if embedding_type == "bert":
        # BERT handles its own embeddings internally
        logger.info("Using BERT embeddings (internal to model)")
        return None

    elif embedding_type == "word2vec":
        dim = config.get("word2vec_dim", 300)
        return _load_word2vec(vocab, dim)

    elif embedding_type == "glove":
        dim = config.get("glove_dim", 300)
        return _load_glove(vocab, dim)

    else:
        raise ValueError(f"Unknown embedding type: {embedding_type}")


def _load_word2vec(vocab: dict[str, int], dim: int = 300) -> nn.Embedding:
    """
    Load Word2Vec embeddings. Uses gensim's downloader for pre-trained vectors.
    Falls back to random initialization for OOV tokens.
    """
    try:
        import gensim.downloader as gensim_api
        logger.info("Loading Word2Vec (word2vec-google-news-300)...")
        w2v_model = gensim_api.load("word2vec-google-news-300")
    except Exception as e:
        logger.warning(f"Could not load Word2Vec model: {e}. Using random init.")
        embedding = nn.Embedding(len(vocab), dim, padding_idx=0)
        nn.init.xavier_uniform_(embedding.weight)
        embedding.weight.data[0] = 0  # padding
        return embedding

    return _build_embedding_from_keyed_vectors(w2v_model, vocab, dim)


def _load_glove(vocab: dict[str, int], dim: int = 300) -> nn.Embedding:
    """
    Load GloVe embeddings. Uses gensim's downloader for pre-trained vectors.
    Falls back to random initialization for OOV tokens.
    """
    try:
        import gensim.downloader as gensim_api
        logger.info(f"Loading GloVe (glove-wiki-gigaword-{dim})...")
        glove_model = gensim_api.load(f"glove-wiki-gigaword-{dim}")
    except Exception as e:
        logger.warning(f"Could not load GloVe model: {e}. Using random init.")
        embedding = nn.Embedding(len(vocab), dim, padding_idx=0)
        nn.init.xavier_uniform_(embedding.weight)
        embedding.weight.data[0] = 0
        return embedding

    return _build_embedding_from_keyed_vectors(glove_model, vocab, dim)


def _build_embedding_from_keyed_vectors(kv, vocab: dict[str, int], dim: int) -> nn.Embedding:
    """Build nn.Embedding from gensim KeyedVectors and a vocabulary."""
    vocab_size = len(vocab)
    weights = np.zeros((vocab_size, dim), dtype=np.float32)
    found = 0

    for word, idx in vocab.items():
        if idx == 0:
            continue  # padding
        if word in kv:
            weights[idx] = kv[word]
            found += 1
        else:
            # Random init for OOV
            weights[idx] = np.random.uniform(-0.25, 0.25, dim)

    coverage = found / max(vocab_size - 1, 1) * 100
    logger.info(f"Embedding coverage: {found}/{vocab_size - 1} tokens ({coverage:.1f}%)")

    embedding = nn.Embedding(vocab_size, dim, padding_idx=0)
    embedding.weight = nn.Parameter(torch.from_numpy(weights))
    embedding.weight.requires_grad = True  # Allow fine-tuning
    return embedding


def build_vocab(texts: list[str], max_vocab: int = 50000) -> dict[str, int]:
    """
    Build a vocabulary from a list of texts.
    Index 0 is reserved for padding, 1 for unknown.
    """
    from collections import Counter

    word_counts: Counter = Counter()
    for text in texts:
        tokens = text.lower().split()
        word_counts.update(tokens)

    vocab = {"<PAD>": 0, "<UNK>": 1}
    for word, _ in word_counts.most_common(max_vocab - 2):
        vocab[word] = len(vocab)

    logger.info(f"Built vocabulary: {len(vocab)} tokens")
    return vocab


def tokenize_for_embedding(texts: list[str], vocab: dict[str, int], max_len: int = 128) -> torch.Tensor:
    """
    Tokenize texts into padded index tensors for non-BERT embeddings.

    Returns:
        Tensor of shape (len(texts), max_len) with token indices.
    """
    unk_idx = vocab.get("<UNK>", 1)
    pad_idx = vocab.get("<PAD>", 0)

    encoded = []
    for text in texts:
        tokens = text.lower().split()[:max_len]
        indices = [vocab.get(t, unk_idx) for t in tokens]
        # Pad
        indices += [pad_idx] * (max_len - len(indices))
        encoded.append(indices)

    return torch.tensor(encoded, dtype=torch.long)
