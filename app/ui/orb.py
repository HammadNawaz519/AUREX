"""AUREX Voice Interaction Surface / Visualizer module.

Re-exports VoiceInteractionSurface as AurexOrb for full backward compatibility
with zero-lag, zero-CPU idle operation.
"""

from app.ui.voice_surface import VoiceInteractionSurface, AurexOrb

__all__ = ["VoiceInteractionSurface", "AurexOrb"]
