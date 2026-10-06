"""toyota-diag: free K-Line diagnostic tooling for 1990s-2000s JDM Toyotas.

v0.1 is a *discovery instrument*: it probes the car's diagnostic port with
every init sequence the community knows about, logs every byte exchanged,
and decodes whatever generic OBD-II the ECU happens to speak. Toyota's
proprietary responses are captured raw so decoding tables can be built
from real probe logs (see README roadmap).
"""

__version__ = "0.1.0"
