"""FL-Healthcare machine-learning package.

Modality-specific models (EHR / ECG / X-ray), dataset loaders, the simulated
data generators and the local training + evaluation code that runs *inside a
hospital node*. Nothing in this package talks to the coordinator database.
"""

#: Shared by the coordinator API and the hospital nodes, so each side can show the other's version.
__version__ = "1.1.0"
