# pdf_panel_export

**PDF 스토리보드 → 컷별 PNG 패널 추출기.** storyboard-previz 파이프라인의 0단계(README 최상위 "1. 스토리보드 촬영/스캔 → 각 컷을 하나의 파일에 정리")를 대신하는 Windows 데스크톱 도구.

CUT/PICTURE/MEMO 형식의 스토리보드 PDF에서, 컷마다 그림(PICTURE) 영역만 16:9로 잘라 `1920x1080` PNG로 저장한다. 페이지 안에 여러 컷이 있으면 각 컷 영역을 모두 지정해 한 번에 일괄 추출할 수 있다.

여기서 나온 PNG는 `storyboard_scene_schema.json`의 `panels[]`를 손으로 작성할 때 참고 이미지로 쓰거나, Seedance 프롬프트의 레퍼런스 바인딩 이미지로 사용한다. (README에 적힌 대로 "VLM 자동 추출 미구현" — 이 도구는 그 앞단인 이미지 정리를 자동화한다.)

## 실행

```bash
cd tools/pdf_panel_export
pip install -r requirements.txt
python main.py
```

Windows에서 Python 없이 배포하려면 PyInstaller로 단일 exe로 묶을 수 있다 (빌드 산출물은 git에 커밋하지 않는다):

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "PDF패널추출" --icon "resources/icon.ico" --add-data "resources/icon.ico;resources" main.py
```

## 사용법

1. **PDF 열기**로 스토리보드 PDF 로드
2. 캔버스에서 왼쪽 드래그로 컷의 PICTURE 영역 지정 (항상 16:9 고정), 오른쪽 패널 좌표 입력으로 미세 조정, 방향키로 1px 단위 이동(Shift+방향키는 10px)
3. 자주 쓰는 크기는 캔버스에서 **오른쪽 드래그**로 프리셋 저장, 이후 목록에서 "적용"으로 재사용
4. 한 페이지에 컷이 여러 개면, 영역을 잡을 때마다 **"+ 현재 영역 추가"**로 이름(예: `cut1`)을 붙여 목록에 쌓는다
5. **"내보내기"** 한 번으로 목록의 모든 영역 × 모든 페이지를 각각 `{저장폴더}/{cut1}/page_001.png ...` 형태로 일괄 저장
6. 같은 스토리보드 양식을 쓰는 다른 PDF에는 **영역 세트 저장/불러오기**로 컷 위치 조합을 재사용 (다른 페이지 크기에는 자동으로 안쪽 클램핑)

자세한 기능/설계 배경은 [PRD.md](./PRD.md) 참고.

## 요구사항

- Python 3.11+
- PySide6, PyMuPDF, Pillow (`requirements.txt`)
