"""Torch device selection for local models."""

from __future__ import annotations


def resolve_torch_device(requested: str) -> str:
    if requested:
        return requested
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"
