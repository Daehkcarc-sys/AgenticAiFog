"""Federated learning stack: dataset prep, local training, FedAvg, FL runner."""

from federated.aggregator import fedavg, scaffold_correction
from federated.fl_runner import run_federated_learning
from federated.model import MiniLogisticRegression, FEATURE_KEYS, LABEL_ORDER
from federated.trainer import train_local

__all__ = [
    "fedavg",
    "scaffold_correction",
    "run_federated_learning",
    "MiniLogisticRegression",
    "FEATURE_KEYS",
    "LABEL_ORDER",
    "train_local",
]

