# exam-maker 작업 규칙

## 시험지 서식 (사용자 고정 요청)
- 시험지 양식은 '창조 예비고사' 서식(changjo 프로필)을 쓴다.
- **지문및보기·문제·선택지 글꼴은 '함초롬바탕'** (신명 중명조는 인쇄가 흐려서 사용하지 않음).
  크기·줄간격·들여쓰기 등 나머지 서식은 그대로 둔다.
- hwpx 생성은 저장소의 `tools/build_exam_hwpx.py`를 사용한다(이미 함초롬바탕으로 수정됨).
  korean-exam-hwpx 스킬의 원본 빌더를 쓸 경우 반드시 글꼴을 함초롬바탕으로 바꿔서 쓴다.
- 웹 제작기 `index.html`의 템플릿도 같은 글꼴로 맞춰 두었다.

```bash
pip install python-hwpx --break-system-packages
python tools/build_exam_hwpx.py 원고.md -o 출력폴더
```
