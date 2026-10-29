from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    name: str
    email: str
    tone: str = "friendly, brief and professional"

    @property
    def first(self) -> str:
        return self.name.split()[0]


PERSONAS: tuple[Persona, ...] = (
    Persona("Alex Kane", "alex.kane@print247.us"),
    Persona("Frank Castle", "frank.castle@print247.us"),
    Persona("Jessica Joe", "jessica.joe@print247.us"),
    Persona("Max Carter", "max.carter@print247.us"),
    Persona("Harry Brook", "harry.brook@print247.us"),
    Persona("Ethan Wilson", "ethan.wilson@print247.us"),
    Persona("Paul Smith", "paul.smith@print247.us"),
    Persona("Brian Tylar", "briantylar@print247.us"),
    Persona("Hazel Grace", "hazel.grace@print247.us"),
)

BY_NAME = {persona.name.lower(): persona for persona in PERSONAS}
BY_EMAIL = {persona.email.lower(): persona for persona in PERSONAS}


def validate_personas() -> list[str]:
    errors: list[str] = []
    if len(PERSONAS) != 9:
        errors.append(f"expected 9 personas, found {len(PERSONAS)}")
    names = [persona.name.lower() for persona in PERSONAS]
    if len(set(names)) != len(names):
        errors.append("duplicate persona names")
    firsts = [persona.first.lower() for persona in PERSONAS]
    if len(set(firsts)) != len(firsts):
        errors.append("duplicate first names")
    for persona in PERSONAS:
        if not persona.email.endswith("@print247.us"):
            errors.append(f"{persona.name} has an unexpected email domain")
    return errors


def persona_for(name: str | None) -> Persona | None:
    if not name:
        return None
    return BY_NAME.get(str(name).strip().lower()) or BY_EMAIL.get(str(name).strip().lower())
