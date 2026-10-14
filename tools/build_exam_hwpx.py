#!/usr/bin/env python3
"""국어 시험지 hwpx 빌더.

구조화된 시험 원고(마크다운 유사 문법, FORMAT.md 참고)를 읽어
2단 문제지(.hwpx)와 정답·해설지(.hwpx)를 생성한다.

서식 프로필:
  changjo (기본) — 사용자 제공 '창조 예비고사' hwp에서 추출한 서식.
    바탕글: 세종학당 본문체 9pt / 지문및보기: 함초롬바탕 8pt(왼쪽 3.5mm, 첫줄 들여쓰기)
    문제: 함초롬바탕 8pt 굵게 / 선택지: 함초롬바탕 8pt 내어쓰기
    교사용정답: 굴림 8pt 흰색(--answer-color로 변경 가능)
    머리글: 한컴 윤고딕 250 26pt 초록(#05771E) + 초록 괘선, 꼬리말 중앙 문구
    지문·보기 상자: 연분홍(#FDC3D6) 테두리 / A4 여백 L18 R18 T10 B5, 2단 간격 8mm
  suneung — 수능형 기본(함초롬바탕 9.5pt, 검정 괘선)

사용법:
    python build_exam_hwpx.py exam.md -o 출력폴더 [--profile changjo]
        [--single-column] [--no-solutions] [--answer-color '#05771E'] [--no-teacher-answers]

필요 패키지: python-hwpx  (pip install python-hwpx --break-system-packages)
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from hwpx.document import HwpxDocument

# ---------------------------------------------------------------------------
# 파서
# ---------------------------------------------------------------------------

_TITLE_RE = re.compile(r"^#\s+(?P<t>.+\S)\s*$")
_META_RE = re.compile(r"^@(?P<k>부제|머리글|꼬리말)\s*:\s*(?P<v>.*\S)\s*$")
_SET_RE = re.compile(r"^##\s*\[(?P<a>\d+)\s*[~∼〜-]\s*(?P<b>\d+)\]\s*(?P<d>.*)$")
_Q_RE = re.compile(r"^##\s*(?P<n>\d+)\.\s*(?P<stem>.*?)(?:\s*[\(\[](?P<p>\d+(?:\.\d+)?)\s*점[\)\]])?\s*$")
_MEMBER_RE = re.compile(r"^###\s*(?P<n>\d+)\.\s*(?P<stem>.*?)(?:\s*[\(\[](?P<p>\d+(?:\.\d+)?)\s*점[\)\]])?\s*$")
_CHOICE_RE = re.compile(r"^\s*(?P<m>[①②③④⑤⑥⑦⑧⑨⑩])\s*(?P<t>.*)$")
_ANS_RE = re.compile(r"^\(정답\)\s*(?P<v>.*\S)\s*$")
_TAG_RE = re.compile(r"^\(태그\)\s*(?P<v>.*\S)\s*$")
_EXPL_RE = re.compile(r"^\(해설\)\s*(?P<v>.*)$")
_BOX_OPEN_RE = re.compile(r"^\((?P<k>지문|보기|상자|조건|자료)\)\s*$")
_BOX_CLOSE_RE = re.compile(r"^\(/(?P<k>지문|보기|상자|조건|자료)\)\s*$")

_BOX_LABELS = {"보기": "< 보  기 >", "조건": "< 조  건 >", "자료": "< 자  료 >", "상자": None, "지문": None}


class ParseError(ValueError):
    def __init__(self, line_no: int, text: str, reason: str) -> None:
        super().__init__(f"{line_no}행: {reason}: {text!r}")


@dataclass
class Box:
    kind: str
    paragraphs: list[str] = field(default_factory=list)


@dataclass
class Question:
    number: str
    stem: str
    points: str | None = None
    body: list = field(default_factory=list)
    choices: list = field(default_factory=list)
    answer: str | None = None
    tag: str | None = None          # 출처 태그 (예: 수특 문학화작)
    explanation: list[str] = field(default_factory=list)


@dataclass
class QuestionSet:
    rng: str
    direction: str
    passage: list = field(default_factory=list)
    members: list[Question] = field(default_factory=list)


@dataclass
class Exam:
    title: str = ""
    subtitle: str = ""
    header: str = ""
    footer: str = ""
    blocks: list = field(default_factory=list)

    def all_questions(self):
        for b in self.blocks:
            if isinstance(b, QuestionSet):
                yield from b.members
            else:
                yield b


def _join_wrapped(lines: list[str]) -> list[str]:
    paras, buf = [], []
    for ln in lines:
        if ln.strip():
            buf.append(ln.strip())
        elif buf:
            paras.append(" ".join(buf))
            buf = []
    if buf:
        paras.append(" ".join(buf))
    return paras


def parse_exam(md: str) -> Exam:
    exam = Exam()
    cur_set: QuestionSet | None = None
    cur_q: Question | None = None
    box: Box | None = None
    box_lines: list[str] = []
    in_passage = False
    passage_lines: list[str] = []
    in_expl = False

    def close_q():
        nonlocal cur_q, in_expl
        if cur_q is None:
            return
        if cur_set is not None and cur_q not in cur_set.members:
            cur_set.members.append(cur_q)
        elif cur_set is None and cur_q not in exam.blocks:
            exam.blocks.append(cur_q)
        cur_q = None
        in_expl = False

    def close_set():
        nonlocal cur_set
        close_q()
        if cur_set is not None:
            exam.blocks.append(cur_set)
            cur_set = None

    for i, raw in enumerate(md.splitlines(), 1):
        line = raw.rstrip()

        if in_passage:
            m = _BOX_CLOSE_RE.match(line)
            if m and m.group("k") == "지문":
                in_passage = False
                if cur_set is None:
                    raise ParseError(i, line, "(지문)은 세트(## [a~b]) 안에서만 사용")
                cur_set.passage.extend(_join_wrapped(passage_lines))
                passage_lines = []
            else:
                passage_lines.append(line)
            continue
        if box is not None:
            m = _BOX_CLOSE_RE.match(line)
            if m and m.group("k") == box.kind:
                box.paragraphs = [l.strip() for l in box_lines if l.strip()]
                target = cur_q.body if cur_q is not None else (cur_set.passage if cur_set else None)
                if target is None:
                    raise ParseError(i, line, "상자가 문항/세트 밖에 있음")
                target.append(box)
                box, box_lines = None, []
            else:
                box_lines.append(line)
            continue

        if not line.strip():
            if in_expl and cur_q is not None:
                in_expl = False
            continue

        m = _META_RE.match(line)
        if m:
            setattr(exam, {"부제": "subtitle", "머리글": "header", "꼬리말": "footer"}[m.group("k")], m.group("v"))
            continue
        m = _TITLE_RE.match(line)
        if m and not exam.title:
            exam.title = m.group("t")
            continue
        m = _SET_RE.match(line)
        if m:
            close_set()
            cur_set = QuestionSet(rng=f"{m.group('a')}~{m.group('b')}", direction=m.group("d").strip())
            continue
        m = _MEMBER_RE.match(line)
        if m:
            if cur_set is None:
                raise ParseError(i, line, "'### N.' 문항이 세트 밖에 있음")
            close_q()
            cur_q = Question(m.group("n"), m.group("stem").strip(), m.group("p"))
            continue
        m = _Q_RE.match(line)
        if m:
            close_set()
            cur_q = Question(m.group("n"), m.group("stem").strip(), m.group("p"))
            continue
        m = _BOX_OPEN_RE.match(line)
        if m:
            in_expl = False
            if m.group("k") == "지문":
                in_passage = True
            else:
                box = Box(kind=m.group("k"))
            continue
        m = _ANS_RE.match(line)
        if m:
            if cur_q is None:
                raise ParseError(i, line, "(정답)이 문항 밖에 있음")
            cur_q.answer = m.group("v")
            in_expl = False
            continue
        m = _TAG_RE.match(line)
        if m:
            if cur_q is None:
                raise ParseError(i, line, "(태그)가 문항 밖에 있음")
            cur_q.tag = m.group("v")
            continue
        m = _EXPL_RE.match(line)
        if m:
            if cur_q is None:
                raise ParseError(i, line, "(해설)이 문항 밖에 있음")
            if m.group("v").strip():
                cur_q.explanation.append(m.group("v").strip())
            in_expl = True
            continue
        m = _CHOICE_RE.match(line)
        if m:
            if cur_q is None:
                raise ParseError(i, line, "선지가 문항 밖에 있음")
            in_expl = False
            cur_q.choices.append((m.group("m"), m.group("t").strip()))
            continue

        if in_expl and cur_q is not None:
            cur_q.explanation.append(line.strip())
        elif cur_q is not None:
            if cur_q.choices:
                mark, t = cur_q.choices[-1]
                cur_q.choices[-1] = (mark, (t + " " + line.strip()).strip())
            else:
                cur_q.body.append(line.strip())
        elif cur_set is not None:
            cur_set.passage.append(line.strip())
        else:
            raise ParseError(i, line, "문항/세트 시작 전의 내용")

    close_set()
    if in_passage or box is not None:
        raise ParseError(0, "", "닫히지 않은 (지문) 또는 상자 블록")
    if not exam.title:
        exam.title = "국어 시험"
    return exam


# ---------------------------------------------------------------------------
# 서식 프로필
# ---------------------------------------------------------------------------

MM = 7200 / 25.4


def _profiles(answer_color: str) -> dict:
    return {
        # 사용자 제공 '창조 예비고사' hwp에서 추출한 서식
        "changjo": {
            "margins": {"left": 18, "right": 18, "top": 10, "bottom": 5, "header": 15, "footer": 10},
            "col_gap_mm": 8.0,
            "col_separator": None,          # 원본은 단 구분선 있음 → "SOLID"로 켜기 가능
            "title_in_body": False,
            "header_title": None,            # 제목은 사용자가 글상자로 직접 삽입 (공간만 비워 둠)
            "no_header": True,
            "footer_style": {"font": "세종학당 본문체", "size": 9, "color": "#1E5B3A"},
            "rule_color": "#1E5B3A", "rule_width": "0.4 mm",
            "box_border": {"color": "#FDC3D6", "width": "0.15 mm"},
            "styles": {
                "body":      dict(font="세종학당 본문체", size=9),
                "direction": dict(font="바탕", size=9, bold=True),
                "passage":   dict(font="함초롬바탕", size=8),
                "question":  dict(font="함초롬바탕", size=8, bold=True),
                "choice":    dict(font="함초롬바탕", size=8),
                "answer":    dict(font="굴림", size=8, color=answer_color),
                "label":     dict(font="KCC도담도담체 B", size=10),
            },
            "para": {
                # 정렬·keep_with_next를 모두 명시해 서식 상속 오염을 차단한다.
                "body":      dict(alignment="JUSTIFY", line_spacing_percent=160,
                                  spacing_before_pt=0, spacing_after_pt=0, keep_with_next=False),
                "direction": dict(alignment="JUSTIFY", line_spacing_percent=160,
                                  spacing_before_pt=4, spacing_after_pt=2, keep_with_next=False),
                "passage":   dict(alignment="JUSTIFY", line_spacing_percent=155, indent_left_mm=3.5,
                                  first_line_indent_mm=5.6, spacing_before_pt=0, spacing_after_pt=0,
                                  keep_with_next=False),
                "question":  dict(alignment="JUSTIFY", line_spacing_percent=165,
                                  spacing_before_pt=5, spacing_after_pt=2, keep_with_next=True),
                # 원본 '선택지' 스타일 그대로: 왼쪽여백 0 + 내어쓰기 9.88mm
                "choice":    dict(alignment="JUSTIFY", line_spacing_percent=155, indent_left_mm=0,
                                  first_line_indent_mm=-9.9, spacing_before_pt=1, spacing_after_pt=0,
                                  keep_with_next=False),
                "answer":    dict(alignment="LEFT", line_spacing_percent=130,
                                  spacing_before_pt=1, spacing_after_pt=0, keep_with_next=False),
            },
        },
        # 수능형 기본
        "suneung": {
            "margins": {"left": 15, "right": 15, "top": 16, "bottom": 13, "header": 8, "footer": 6},
            "col_gap_mm": 6.0,
            "col_separator": "SOLID",
            "title_in_body": True,
            "header_title": None,
            "rule_color": "#000000", "rule_width": "0.4 mm",
            "box_border": {"color": "#000000", "width": "0.15 mm"},
            "styles": {
                "body":      dict(size=9.5),
                "direction": dict(size=9.5, bold=True),
                "passage":   dict(size=9.5),
                "question":  dict(size=9.5, bold=True),
                "choice":    dict(size=9.5),
                "answer":    dict(size=8.5, color=answer_color),
                "label":     dict(size=9.5),
            },
            "para": {
                "body":      dict(alignment="JUSTIFY", line_spacing_percent=160,
                                  spacing_before_pt=0, spacing_after_pt=0, keep_with_next=False),
                "direction": dict(alignment="JUSTIFY", line_spacing_percent=160,
                                  spacing_before_pt=6, spacing_after_pt=2, keep_with_next=False),
                "passage":   dict(alignment="JUSTIFY", line_spacing_percent=160,
                                  first_line_indent_mm=3, spacing_before_pt=0, spacing_after_pt=0,
                                  keep_with_next=False),
                "question":  dict(alignment="JUSTIFY", line_spacing_percent=160,
                                  spacing_before_pt=6, spacing_after_pt=2,
                                  indent_left_mm=5, first_line_indent_mm=-5, keep_with_next=True),
                "choice":    dict(alignment="JUSTIFY", line_spacing_percent=160, indent_left_mm=0,
                                  first_line_indent_mm=-4, spacing_before_pt=1, spacing_after_pt=0,
                                  keep_with_next=False),
                "answer":    dict(alignment="LEFT", line_spacing_percent=130,
                                  spacing_before_pt=1, spacing_after_pt=0, keep_with_next=False),
            },
        },
    }


# ---------------------------------------------------------------------------
# 렌더러
# ---------------------------------------------------------------------------

_HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def _register_fonts(doc: HwpxDocument, names: set[str]) -> None:
    """header.xml의 모든 fontface(lang)에 글꼴을 등록한다."""
    try:
        header = doc._root._headers[0]
        root = header._element
    except Exception:
        return
    changed = False
    for fontface in root.findall(f".//{_HH}fontface"):
        fonts = fontface.findall(f"{_HH}font")
        existing = {f.get("face") for f in fonts}
        next_id = max((int(f.get("id", "0")) for f in fonts), default=-1) + 1
        for name in sorted(names):
            if name in existing:
                continue
            el = fontface.makeelement(f"{_HH}font", {
                "id": str(next_id), "face": name, "type": "TTF", "isEmbedded": "0"})
            ti = el.makeelement(f"{_HH}typeInfo", {
                "familyType": "FCAT_GOTHIC", "weight": "6", "proportion": "4",
                "contrast": "0", "strokeVariation": "1", "armStyle": "1",
                "letterform": "1", "midline": "1", "xHeight": "1"})
            el.append(ti)
            fontface.append(el)
            next_id += 1
            changed = True
        fontface.set("fontCnt", str(len(fontface.findall(f"{_HH}font"))))
    if changed:
        try:
            header.mark_dirty()
        except Exception:
            pass


class Renderer:
    _INLINE_RE = re.compile(r"(\*\*.+?\*\*|__.+?__)")

    def __init__(self, profile: dict, two_column: bool = True, teacher_answers: bool = True):
        self.p = profile
        self.two_column = two_column
        self.teacher_answers = teacher_answers
        self.doc = HwpxDocument.new()
        d = self.doc
        d.set_page_setup(paper_size="A4", margins_mm=profile["margins"])
        fonts = {v["font"] for v in profile["styles"].values() if "font" in v}
        if profile.get("header_title"):
            fonts.add(profile["header_title"]["font"])
        _register_fonts(d, fonts)
        self.st = {k: d.ensure_run_style(**v) for k, v in profile["styles"].items()}
        self.box_border = d.ensure_border_fill(
            border_color=profile["box_border"]["color"],
            border_width=profile["box_border"]["width"])
        self.plain_border = d.ensure_border_fill(border_color="#000000", border_width="0.12 mm")
        self._var_cache: dict = {}
        # 본문 폭(mm): A4 210 - 좌우 여백
        m = profile["margins"]
        self.content_w = 210 - m["left"] - m["right"]
        self.col_w = (self.content_w - profile["col_gap_mm"]) / 2 if two_column else self.content_w

    # -- 저수준 도우미 ------------------------------------------------------
    def _variant(self, base, **flags):
        key = (base, tuple(sorted(flags.items())))
        if key not in self._var_cache:
            self._var_cache[key] = self.doc.ensure_run_style(base_char_pr_id=base, **flags)
        return self._var_cache[key]

    def _fill_runs(self, p, text, base):
        for tok in self._INLINE_RE.split(text):
            if not tok:
                continue
            if tok.startswith("**") and tok.endswith("**") and len(tok) > 4:
                p.add_run(tok[2:-2], char_pr_id_ref=self._variant(base, bold=True))
            elif tok.startswith("__") and tok.endswith("__") and len(tok) > 4:
                p.add_run(tok[2:-2], char_pr_id_ref=self._variant(base, underline=True))
            else:
                p.add_run(tok, char_pr_id_ref=base)

    def para(self, text="", role="body", style=None, **extra_fmt):
        d = self.doc
        base = style or self.st.get(role, self.st["body"])
        # inherit_style=False: 이전 문단 서식(정렬 등)이 전염되지 않게 한다.
        if "**" in text or "__" in text:
            p = d.add_paragraph("", char_pr_id_ref=base, include_run=False, inherit_style=False)
            self._fill_runs(p, text, base)
        else:
            p = d.add_paragraph(text, char_pr_id_ref=base, inherit_style=False)
        opts = dict(self.p["para"].get(role, {"alignment": "JUSTIFY", "line_spacing_percent": 160}))
        opts.update(extra_fmt)
        # 동일 서식은 paraPr을 재사용
        cache = getattr(self, "_pp_cache", {})
        key = tuple(sorted((k, str(v)) for k, v in opts.items()))
        if key in cache:
            p.para_pr_id_ref = cache[key]
        else:
            try:
                d.set_paragraph_format(paragraph_index=len(d.paragraphs) - 1, **opts)
                cache[key] = p.para_pr_id_ref
                self._pp_cache = cache
            except Exception as e:
                print(f"[경고] 문단 서식 적용 실패({role}): {e}", file=sys.stderr)
        return p

    def _set_columns_inplace(self, count: int, gap_units: int):
        """구역의 기본 colPr(1단)을 직접 수정해 다단을 적용한다."""
        HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
        try:
            section = self.doc.sections[0]
            el = section.element.find(f".//{HP}colPr")
            if el is None:
                raise ValueError("colPr 없음")
            el.set("type", "NEWSPAPER")
            el.set("layout", "LEFT")
            el.set("colCount", str(count))
            el.set("sameSz", "1")
            el.set("sameGap", str(gap_units))
            section.mark_dirty()
        except Exception as e:
            print(f"[경고] 다단 적용 실패: {e}", file=sys.stderr)

    def _border_para_pr(self, align="CENTER", side_top=False):
        """머리글/꼬리말용 괘선 문단 paraPr을 임시 문단으로 생성해 ID만 취득."""
        d = self.doc
        d.add_paragraph("", include_run=False)
        idx = len(d.paragraphs) - 1
        try:
            d.set_paragraph_format(paragraph_index=idx, alignment=align, bottom_border=True,
                                   border_color=self.p["rule_color"], border_width=self.p["rule_width"])
            pid = d.paragraphs[idx].para_pr_id_ref
        except Exception:
            pid = None
        try:
            d.remove_paragraph(d.paragraphs[idx])
        except Exception:
            pass
        return pid

    def _apply_hf_border(self, wrapper, para_index=0, align="CENTER"):
        pid = self._border_para_pr(align=align)
        if pid is None:
            return
        try:
            paras = wrapper.paragraphs
            paras[para_index].element.set("paraPrIDRef", str(pid))
        except Exception:
            pass

    def _boxed_pp(self, role, centered=False):
        """문단 테두리(분홍 상자) paraPr — 단·페이지 경계에서 자연스럽게 나뉜다."""
        key = ("boxed", role, centered)
        cache = getattr(self, "_pp_cache", {})
        if key in cache:
            return cache[key]
        d = self.doc
        opts = dict(self.p["para"].get(role, {"alignment": "JUSTIFY", "line_spacing_percent": 160}))
        if centered:
            opts["alignment"] = "CENTER"
            opts.pop("indent_left_mm", None)
            opts.pop("first_line_indent_mm", None)
        d.add_paragraph("", include_run=False, inherit_style=False)
        try:
            d.set_paragraph_format(paragraph_index=len(d.paragraphs) - 1, **opts)
        except Exception as e:
            print(f"[경고] 상자 문단 서식 실패: {e}", file=sys.stderr)
        base_id = d.paragraphs[-1].para_pr_id_ref
        try:
            d.remove_paragraph(d.paragraphs[-1])
        except Exception:
            pass
        header = d._root.headers[0]
        pid = header.ensure_paragraph_format(base_para_pr_id=base_id, border={
            "borderFillIDRef": self.box_border,
            "offsetLeft": "0", "offsetRight": "0", "offsetTop": "283", "offsetBottom": "283",
            "connect": "1", "ignoreMargin": "0"})
        cache[key] = pid
        self._pp_cache = cache
        return pid

    def box(self, box: Box, width_mm: float = 0, content_role="passage"):
        """테두리 상자 = 연결된 문단 테두리 (원본 '지문및보기' 방식)."""
        label = _BOX_LABELS.get(box.kind)
        base = self.st.get(content_role, self.st["body"])
        made = []
        if label:
            p = self.doc.add_paragraph("", include_run=False, inherit_style=False)
            self._fill_runs(p, label, self.st["label"])
            p.para_pr_id_ref = self._boxed_pp(content_role, centered=True)
            made.append(p)
        for ln in box.paragraphs:
            p = self.doc.add_paragraph("", include_run=False, inherit_style=False)
            self._fill_runs(p, ln, base)
            p.para_pr_id_ref = self._boxed_pp(content_role)
            made.append(p)
        return made

    def choices(self, items):
        texts = [f"{m} {t}".strip() for m, t in items]
        merged = "   ".join(texts)
        if all(len(t) <= 10 for t in texts) and len(merged) <= 52:
            self.para(merged, role="choice", indent_left_mm=0, first_line_indent_mm=0)
        else:
            for t in texts:
                self.para(t, role="choice")

    # -- 문제지 -------------------------------------------------------------
    def render_exam(self, exam: Exam):
        d = self.doc
        p = self.p
        header_title = exam.header or exam.title
        if p.get("header_title"):
            ht = p["header_title"]
            content = [{
                "align": "CENTER",
                "children": [{"type": "run", "text": header_title,
                              "font": ht["font"], "size": ht["size"], "color": ht["color"],
                              "bold": ht.get("bold", False)}],
            }]
            if exam.subtitle:
                content.append({"align": "CENTER",
                                "children": [{"type": "run", "text": exam.subtitle, "size": 9}]})
            hdr = d.set_header_content(content)
            self._apply_hf_border(hdr, len(content) - 1, "CENTER")
        elif not p.get("no_header"):
            d.set_header_text(header_title)
        if exam.footer:
            fs = p.get("footer_style", {"size": 9})
            ftr = d.set_footer_content([
                {"align": "CENTER", "children": [{"type": "run", "text": ""}]},  # 괘선용 빈 줄
                {"align": "CENTER", "children": [{"type": "run", "text": exam.footer, **fs}]},
            ])
            self._apply_hf_border(ftr, 0, "CENTER")

        # 빈 문서의 구역에 이미 1단 colPr이 있으므로, 새로 추가하지 말고 그것을 2단으로 수정한다.
        # (단 정의가 두 개면 한글이 첫 번째 1단 정의를 따라 다단이 무시된다.)
        if self.two_column:
            self._set_columns_inplace(2, int(p["col_gap_mm"] * MM))

        if p["title_in_body"]:
            t_style = self.doc.ensure_run_style(bold=True, size=16)
            self.para(exam.title, style=t_style, alignment="CENTER")
            if exam.subtitle:
                s_style = self.doc.ensure_run_style(size=10)
                self.para(exam.subtitle, style=s_style, alignment="CENTER")
            self.para("", role="body", bottom_border=True,
                      border_color=p["rule_color"], border_width=p["rule_width"], spacing_after_pt=6)

        for b in exam.blocks:
            if isinstance(b, QuestionSet):
                direction = b.direction or "다음 글을 읽고 물음에 답하시오."
                self.para(f"※[{b.rng}] {direction}", role="direction")
                pas_boxes = [x for x in b.passage]
                # 지문 문단들은 하나의 상자에 모아 담는다 (창조 서식)
                text_paras = [x for x in pas_boxes if not isinstance(x, Box)]
                if text_paras:
                    self.box(Box(kind="지문", paragraphs=text_paras), self.col_w - 1)
                for item in pas_boxes:
                    if isinstance(item, Box):
                        self.box(item, self.col_w - 1)
                for q in b.members:
                    self.render_question(q)
            else:
                self.render_question(b)

    def render_question(self, q: Question):
        pts = f" ({q.points}점)" if q.points else ""
        self.para(f"{q.number}. {q.stem}{pts}", role="question")
        for item in q.body:
            if isinstance(item, Box):
                self.box(item, self.col_w - 3)
            else:
                self.para(item, role="passage", indent_left_mm=0, first_line_indent_mm=0)
        if q.choices:
            self.choices(q.choices)
        if self.teacher_answers and q.answer:
            tag = f"[{q.tag}] " if q.tag else ""
            self.para(f"{tag}{q.answer}", role="answer")

    # -- 해설지 -------------------------------------------------------------
    def render_solutions(self, exam: Exam):
        d = self.doc
        title = f"{exam.title} — 정답 및 해설"
        d.set_header_text(title)
        t_style = d.ensure_run_style(bold=True, size=14)
        self.para(exam.title, style=t_style, alignment="CENTER")
        self.para("정답 및 해설", role="direction", alignment="CENTER")
        self.para("", role="body", bottom_border=True,
                  border_color=self.p["rule_color"], border_width=self.p["rule_width"],
                  spacing_after_pt=8)
        qs = list(exam.all_questions())
        chunk = 10
        for s in range(0, len(qs), chunk):
            part = qs[s:s + chunk]
            tbl = d.add_table(2, len(part) + 1, width=int(self.content_w * MM),
                              border_fill_id_ref=self.plain_border)
            tbl.set_cell_text(0, 0, "문항")
            tbl.set_cell_text(1, 0, "정답")
            for j, q in enumerate(part, 1):
                tbl.set_cell_text(0, j, str(q.number))
                tbl.set_cell_text(1, j, q.answer or "-")
            self.para("", role="body")
        for q in qs:
            self.para(f"{q.number}. 정답 {q.answer or '-'}", role="question")
            for ln in q.explanation or ["(해설 없음)"]:
                self.para(ln, role="body", alignment="JUSTIFY")

    def save(self, path: Path):
        self.doc.save_to_path(str(path))
        report = self.doc.validate()
        if report.issues:
            print(f"[경고] {path.name} 유효성 이슈: {report.issues}", file=sys.stderr)
        return report


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="국어 시험 원고 → hwpx 시험지/해설지")
    ap.add_argument("input", help="시험 원고(.md)")
    ap.add_argument("-o", "--outdir", default=".", help="출력 폴더")
    ap.add_argument("--profile", default="changjo", choices=["changjo", "suneung"], help="서식 프로필")
    ap.add_argument("--single-column", action="store_true", help="문제지를 1단으로")
    ap.add_argument("--no-solutions", action="store_true", help="해설지 생성 생략")
    ap.add_argument("--answer-color", default="#FFFFFF",
                    help="교사용정답 글자색 (기본 흰색=인쇄 시 안 보임, 교사 확인용은 '#FF0000' 등)")
    ap.add_argument("--no-teacher-answers", action="store_true", help="문제지에 교사용정답 미표기")
    ap.add_argument("--name", default=None, help="출력 파일명 접두어(기본: 제목)")
    args = ap.parse_args()

    md = Path(args.input).read_text(encoding="utf-8")
    exam = parse_exam(md)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = args.name or re.sub(r'[\\/:*?"<>|]', "_", exam.title)[:40]
    profile = _profiles(args.answer_color)[args.profile]

    r = Renderer(profile, two_column=not args.single_column,
                 teacher_answers=not args.no_teacher_answers)
    r.render_exam(exam)
    p1 = outdir / f"{stem}_문제지.hwpx"
    r.save(p1)
    print(f"생성: {p1}")

    if not args.no_solutions:
        r2 = Renderer(profile, two_column=False, teacher_answers=False)
        r2.render_solutions(exam)
        p2 = outdir / f"{stem}_해설지.hwpx"
        r2.save(p2)
        print(f"생성: {p2}")

    n = len(list(exam.all_questions()))
    missing = [q.number for q in exam.all_questions() if not q.answer]
    print(f"문항 수: {n}" + (f" / 정답 누락: {missing}" if missing else ""))


if __name__ == "__main__":
    main()
