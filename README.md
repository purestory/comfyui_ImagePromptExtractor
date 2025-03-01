# 이미지 프롬프트 추출기 (Image Prompt Extractor)

ComfyUI로 생성된 이미지에서 프롬프트 텍스트를 추출하는 확장 노드입니다.

## 기능

- PNG 이미지 메타데이터에서 프롬프트 추출
- ComfyUI 워크플로우 정보에서 한글 프롬프트 추출
- 유니코드 이스케이프 시퀀스 자동 변환
- DeepTranslatorTextNode와 같은 한글 입력 노드 지원

## 설치 방법

### 수동 설치

1. ComfyUI 폴더 내 `custom_nodes` 디렉토리로 이동
2. 이 저장소를 클론:
   ```bash
   git clone https://github.com/purestory/comfyui-image-prompt-extractor
   ```
3. ComfyUI 재시작

### ComfyUI Manager로 설치

1. ComfyUI Manager에서 "이미지 프롬프트 추출기" 검색
2. "설치" 버튼 클릭

## 사용 방법

1. ComfyUI 워크플로우에 "이미지 프롬프트 추출기" 노드 추가
2. "image" 입력에 이미지 연결
3. "image_path" 입력에 이미지 파일 경로 입력
4. 노드가 메타데이터에서 추출한 프롬프트를 출력합니다

## 지원하는 메타데이터 형식

- ComfyUI 내장 메타데이터 (prompt, workflow)
- DeepTranslatorTextNode의 한글 텍스트
- 일반 "parameters" 필드
- EXIF 메타데이터
- 'Comment' 필드

## 라이선스

MIT 라이선스

## 제작자

- [purestory](https://github.com/purestory)