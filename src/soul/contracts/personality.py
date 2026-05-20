from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class SoulPersona(BaseModel):
    """Character card that defines Soul's personality and speaking style.

    This is the ONLY place where Soul's identity is defined. All other
    modules (ReasoningNode, QQConnector, etc.) read from this model.

    Users edit data/persona.yaml to change Soul's character — no code changes needed.
    """

    name: str = "Soul"
    description: str = ""
    personality: str = ""
    speaking_style: str = ""
    interests: List[str] = Field(default_factory=list)
    avoid_topics: List[str] = Field(default_factory=list)
    background: str = ""

    def to_system_prompt(self) -> str:
        """Build the role-defining portion of the system prompt.

        Describes WHO Soul is, not WHAT Soul should do.
        The LLM naturally derives behaviour from the character description.
        """
        parts = [
            f"你是 {self.name}。以下是你的人设，请始终保持这个身份：",
            "",
            "关于你：",
            f"- 背景：{self.background}" if self.background else "",
        ]
        if self.personality:
            parts.append(f"- 性格：{self.personality}")
        if self.interests:
            parts.append(f"- 兴趣爱好：{'、'.join(self.interests)}")
        if self.speaking_style:
            parts.append(f"- 说话方式：{self.speaking_style}")
        if self.avoid_topics:
            parts.append(f"- 你会避免聊：{'、'.join(self.avoid_topics)}")

        return "\n".join(p for p in parts if p)
