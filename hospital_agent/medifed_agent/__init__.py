"""MediFed Hospital Agent: connects one hospital's computer to a MediFed coordinator.

Trains on the hospital's own data on this machine and sends only model weights, record counts and summary
metrics. It contains the node client, the model definitions, the local data check and the training and
evaluation code, and nothing of the server, the dashboard or the database.
"""

__version__ = "1.0.0"
