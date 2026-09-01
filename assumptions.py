"""가정값 레지스트리 — 코드에 박히는 수치의 출처를 강제로 드러낸다.

■ 왜 있나
  블록아웃의 수치(칸 치수·기둥 높이·처마 깊이 등)는 실측 도면이 있으면 사실이고,
  없으면 가정이다. 문제는 둘이 코드에서 똑같이 생겼다는 것이다. 주석에
  "민가는 반 칸 안팎" 같은 문장을 달아두면 다음에 읽는 사람(다른 AI 포함)은
  그걸 출처로 읽지만, 실제로는 지어낸 값일 수 있다. 실제로 그렇게 커밋된 적이 있다.

■ 어떻게 막나
  값을 A() 로 등록해야 하고, A() 는 source 를 인자로 요구한다. 출처를 모르면
  source=None 을 명시적으로 써야 하며, 그 값은 '미확인'으로 분류되어
  실행할 때마다 화면에 목록으로 뜬다. 주석에 숨을 수 없다.

  A() 는 값을 그대로 돌려주므로 상수는 여전히 평범한 float 다.
  (KAN * bays 같은 산술이 그대로 동작한다)

■ 쓰는 법
    from assumptions import A, report, unverified, write_sidecar

    KAN   = A("KAN", 2.4, "m", "1칸(주간거리)", source=None)          # 미확인
    COL_D = A("COL_D", 0.21, "m", "기둥 한 변",
              source="민가는 방주만 허용(조선시대 원기둥 금지). 6~8치의 중간값")

    print("\\n".join(report()))        # 실행할 때마다 출처 현황 출력
    if strict and unverified():        # CI 나 --strict 에서 막고 싶을 때
        raise SystemExit(1)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Assumption:
    """코드에 박힌 수치 하나와 그 출처."""
    name: str
    value: float
    unit: str
    note: str
    source: str | None      # None = 미확인 가정. 지어낸 값도 여기 해당한다.

    @property
    def verified(self) -> bool:
        return bool(self.source)


_REGISTRY: list[Assumption] = []


def A(name: str, value: float, unit: str, note: str, *, source: str | None) -> float:
    """가정값을 등록하고 값을 그대로 돌려준다.

    source 는 키워드 전용 필수 인자다. 출처를 적지 않고는 상수를 만들 수 없고,
    모르면 source=None 이라고 명시해야 한다 — 그 순간 미확인 목록에 올라간다.
    """
    if not name or not isinstance(name, str):
        raise ValueError(f"가정값 이름이 필요하다: {name!r}")
    if any(a.name == name for a in _REGISTRY):
        raise ValueError(f"가정값 이름 중복: {name!r}")
    _REGISTRY.append(Assumption(name, value, unit, note, source))
    return value


def all_assumptions() -> list[Assumption]:
    return list(_REGISTRY)


def unverified() -> list[Assumption]:
    """출처가 없는 가정값. 비어 있지 않으면 그 수치들은 전부 추측이다."""
    return [a for a in _REGISTRY if not a.verified]


def reset() -> None:
    """테스트용. 레지스트리를 비운다."""
    _REGISTRY.clear()


def report() -> list[str]:
    """실행 로그에 그대로 찍을 줄 목록. 미확인 값을 숨기지 않는다."""
    total = len(_REGISTRY)
    bad = unverified()
    lines = [f"[가정] 총 {total}개 · 출처 있음 {total - len(bad)}개 · 미확인 {len(bad)}개"]
    if bad:
        lines.append("[가정] ── 미확인(=추측). 실측 자료가 생기면 우선 교체할 것 ──")
        for a in bad:
            lines.append(f"[가정]    {a.name:<16}{a.value:>8g} {a.unit:<3} {a.note}")
    return lines


def write_sidecar(path: str | Path, title: str = "가정값") -> Path:
    """가정값 출처를 마크다운으로 남긴다.

    씬 스키마가 additionalProperties:false 라 JSON 안에 넣을 수 없으므로,
    산출물 옆에 별도 파일로 둬서 출처가 함께 따라가게 한다.
    """
    p = Path(path)
    rows = ["| 이름 | 값 | 설명 | 출처 |", "|---|---|---|---|"]
    for a in sorted(_REGISTRY, key=lambda x: (not x.verified, x.name)):
        src = a.source if a.verified else "**미확인 (추측)**"
        rows.append(f"| `{a.name}` | {a.value:g} {a.unit} | {a.note} | {src} |")
    body = [
        f"# {title}",
        "",
        "이 표는 `assumptions.py` 레지스트리에서 자동 생성된다. 직접 고치지 말 것.",
        "",
        f"출처 있음 **{len(_REGISTRY) - len(unverified())}** / 미확인 **{len(unverified())}**",
        "",
        *rows,
        "",
    ]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(body), encoding="utf-8")
    return p


# ---- 자체 검증 ------------------------------------------------------------

def _demo():
    reset()
    a = A("X", 1.5, "m", "테스트", source="어떤 문헌")
    b = A("Y", 2.0, "m", "테스트2", source=None)
    assert a == 1.5 and b == 2.0, "A()는 값을 그대로 돌려줘야 한다"
    assert isinstance(a, float)

    assert len(all_assumptions()) == 2
    assert [x.name for x in unverified()] == ["Y"], "출처 없는 것만 미확인이어야 한다"

    rep = "\n".join(report())
    assert "미확인 1개" in rep
    assert "Y" in rep, "미확인 값은 목록에 이름이 떠야 한다"
    assert "X " not in rep.split("──")[-1], "출처 있는 값은 미확인 목록에 없어야 한다"

    # 이름 중복은 거부 (같은 상수를 두 번 등록해 출처가 갈리는 것 방지)
    try:
        A("X", 9.9, "m", "중복", source=None)
    except ValueError as e:
        assert "중복" in str(e)
    else:
        raise AssertionError("이름 중복이 통과됨")

    # source 는 키워드 전용 필수 - 빠뜨리면 TypeError
    try:
        A("Z", 1.0, "m", "출처 누락")  # type: ignore[call-arg]
    except TypeError:
        pass
    else:
        raise AssertionError("source 없이 등록이 통과됨")

    reset()
    assert all_assumptions() == []
    print("assumptions.py: OK")


if __name__ == "__main__":
    _demo()
