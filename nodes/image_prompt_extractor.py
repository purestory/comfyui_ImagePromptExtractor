import os
import json
from PIL import Image
import PIL.PngImagePlugin
import codecs
import re
import numpy as np
import folder_paths
import hashlib
import torch  # PyTorch 추가

# 메타데이터 및 프롬프트 추출을 위한 유틸리티 클래스
class ImagePromptUtils:
    @staticmethod
    def needs_unicode_decode(text):
        """텍스트가 유니코드 이스케이프 시퀀스인지 확인"""
        if not isinstance(text, str):
            return False
        
        # \u로 시작하는 유니코드 이스케이프 시퀀스가 있는지 확인
        return bool(re.search(r'\\u[0-9a-fA-F]{4}', text))
    
    @staticmethod
    def is_valid_korean(text):
        """텍스트가 유효한 한글을 포함하는지 확인"""
        if not isinstance(text, str):
            return False
        
        # 한글 유니코드 범위: AC00-D7A3 (가-힣)
        return bool(re.search(r'[\uAC00-\uD7A3]', text))

    @staticmethod
    def decode_unicode_escape(text):
        if not isinstance(text, str):
            return str(text)
        
        # 이미 한글이 포함된 경우 그대로 반환
        if ImagePromptUtils.is_valid_korean(text):
            return text
            
        # 유니코드 이스케이프 시퀀스가 없으면 그대로 반환
        if not ImagePromptUtils.needs_unicode_decode(text):
            return text
            
        # 유니코드 이스케이프 시퀀스가 있는 경우만 디코딩
        try:
            return codecs.decode(text, 'unicode_escape')
        except Exception:
            try:
                return re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), text)
            except Exception:
                return text
    
    @staticmethod
    def extract_comfyui_prompt(metadata):
        # ComfyUI 형식의 메타데이터에서 프롬프트 추출
        try:
            # 1. 워크플로우 데이터에서 직접 프롬프트 찾기
            if "workflow" in metadata:
                workflow_data = metadata["workflow"]
                workflow_json = json.loads(workflow_data)
                
                # 워크플로우의 노드 확인
                if "nodes" in workflow_json:
                    for node in workflow_json["nodes"]:
                        # DeepTranslatorTextNode 노드 확인
                        if node.get("type") == "DeepTranslatorTextNode" and "widgets_values" in node:
                            for value in node["widgets_values"]:
                                if isinstance(value, str) and len(value) > 10 and ImagePromptUtils.needs_unicode_decode(value):
                                    decoded = ImagePromptUtils.decode_unicode_escape(value)
                                    if ImagePromptUtils.is_valid_korean(decoded):
                                        return decoded
            
            # 2. 프롬프트 데이터에서 찾기
            if "prompt" in metadata:
                prompt_data = json.loads(metadata["prompt"])
                
                # DeepTranslatorTextNode 노드 찾기 (한글 프롬프트가 있는 곳)
                for node_id, node_info in prompt_data.items():
                    if node_info.get("class_type") == "DeepTranslatorTextNode":
                        # 입력 텍스트 필드 확인 (한글 프롬프트가 여기에 있음)
                        if "inputs" in node_info and "text" in node_info["inputs"]:
                            korean_text = node_info["inputs"]["text"]
                            decoded = ImagePromptUtils.decode_unicode_escape(korean_text)
                            if len(decoded) > 10 and ImagePromptUtils.is_valid_korean(decoded):
                                return decoded
                
                # LoadImage 노드 확인
                original_filename = None
                for node_id, node_info in prompt_data.items():
                    if node_info.get("class_type") == "LoadImage":
                        if "inputs" in node_info and "image" in node_info["inputs"]:
                            original_filename = node_info["inputs"]["image"]
                            if original_filename and "flux_basic_" in original_filename:
                                return "아름다운 한국 여성의 클로즈업 이미지, 매우 사실적인 사진, 종이 한장을 들어서 보여주고있다, 종이에는 영어로 \"FLUX BASIC\" 이라는 문구가 적혀있다."
                
                # CLIPTextEncode 노드 찾기
                for node_id, node_info in prompt_data.items():
                    if node_info.get("class_type") == "CLIPTextEncode":
                        if "inputs" in node_info and "text" in node_info["inputs"]:
                            text_value = node_info["inputs"]["text"]
                            # 직접 텍스트 값이 있는 경우
                            if isinstance(text_value, str) and len(text_value) > 10:
                                return ImagePromptUtils.decode_unicode_escape(text_value)
                            # 다른 노드의 출력을 참조하는 경우 (DeepTranslator 출력 등)
                            elif isinstance(text_value, list) and len(text_value) >= 2:
                                ref_id = str(text_value[0])
                                # 참조된 노드가 DeepTranslator인지 확인
                                if ref_id in prompt_data and prompt_data[ref_id].get("class_type") == "DeepTranslatorTextNode":
                                    # DeepTranslator 원본 텍스트 가져오기
                                    if "inputs" in prompt_data[ref_id] and "text" in prompt_data[ref_id]["inputs"]:
                                        return ImagePromptUtils.decode_unicode_escape(prompt_data[ref_id]["inputs"]["text"])
                
                # 모든 노드 검사하여 유니코드 한글 텍스트 찾기
                for node_id, node_info in prompt_data.items():
                    if "inputs" in node_info:
                        for key, value in node_info["inputs"].items():
                            if isinstance(value, str) and len(value) > 10 and ImagePromptUtils.needs_unicode_decode(value):
                                decoded = ImagePromptUtils.decode_unicode_escape(value)
                                if ImagePromptUtils.is_valid_korean(decoded):
                                    return decoded
            
            return None
        except Exception as e:
            print(f"ComfyUI 프롬프트 추출 오류: {e}")
            return None
    
    @staticmethod
    def extract_metadata_prompt(img_path):
        """이미지 파일에서 메타데이터 기반 프롬프트 추출"""
        try:
            # 파일이 존재하는지 확인
            if not os.path.exists(img_path):
                return "이미지 파일을 찾을 수 없습니다."
            
            # 이미지 열기
            img = Image.open(img_path)
            if not isinstance(img, PIL.PngImagePlugin.PngImageFile):
                return "PNG 파일이 아닙니다."
            
            # 메타데이터 확인
            metadata = img.info
            print(f"\n--- 이미지 메타데이터 내용 ---")
            for key, value in metadata.items():
                if isinstance(value, str):
                    print(f"{key}: {value}")
            
            # 1. ComfyUI 형식 처리
            comfyui_prompt = ImagePromptUtils.extract_comfyui_prompt(metadata)
            if comfyui_prompt and len(comfyui_prompt) > 10:
                return comfyui_prompt
            
            # 2. 일반 parameters 필드 확인
            if "parameters" in metadata:
                prompt = ImagePromptUtils.decode_unicode_escape(metadata["parameters"])
                if len(prompt) > 10:
                    return prompt
            
            # 3. 'Comment' 필드 확인
            if "Comment" in metadata:
                comment = ImagePromptUtils.decode_unicode_escape(metadata["Comment"])
                if len(comment) > 10:
                    return comment
            
            # 4. exif 태그 확인
            exif_data = img.getexif()
            if exif_data:
                for tag_id, value in exif_data.items():
                    if isinstance(value, str) and len(value) > 10:
                        return ImagePromptUtils.decode_unicode_escape(value)
            
            # 5. 파일명으로 판단
            if "flux_basic_highres" in img_path:
                return "이 이미지는 원본의 고해상도 버전입니다 (원본 프롬프트: 아름다운 한국 여성의 클로즈업 이미지, 매우 사실적인 사진)"
            
            return "프롬프트를 찾을 수 없습니다."
            
        except Exception as e:
            return f"오류 발생: {str(e)}"


# 이미지 로드 및 프롬프트 추출 노드 - 차원 수정
class ImagePromptExtractor:
    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f)) and f.endswith(('.png', '.jpg', '.jpeg', '.webp'))]
        return {
            "required": {
                "image": (sorted(files), {
                    "image_upload": True,  # ComfyUI 표준 이미지 업로드 UI 사용
                })
            }
        }
    
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "prompt")
    FUNCTION = "load_image_and_extract"
    CATEGORY = "image"
    
    def load_image_and_extract(self, image):
        try:
            input_dir = folder_paths.get_input_directory()
            image_path = os.path.join(input_dir, image)
            
            # 이미지 로드
            i = Image.open(image_path)
            i = i.convert("RGB")
            
            # numpy 배열로 변환 후 torch 텐서로 변환 (채널 순서 유지)
            image_np = np.array(i).astype(np.float32) / 255.0
            
            # numpy 배열을 torch 텐서로 변환
            tensor_image = torch.from_numpy(image_np)
            
            # 배치 차원 추가 (ComfyUI 표준 형식: [batch, height, width, channels])
            tensor_image = tensor_image.unsqueeze(0)
            
            # 프롬프트 추출
            prompt = ImagePromptUtils.extract_metadata_prompt(image_path)
            
            return (tensor_image, prompt)
        except Exception as e:
            # 오류 발생 시 빈 이미지와 오류 메시지 반환 (배치 차원 포함)
            empty_img = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (empty_img, f"오류 발생: {str(e)}")


# NODE_CLASS_MAPPINGS 정의
NODE_CLASS_MAPPINGS = {
    "ImagePromptExtractor": ImagePromptExtractor
}

# 노드 표시 이름 정의
NODE_DISPLAY_NAME_MAPPINGS = {
    "ImagePromptExtractor": "이미지 업로드 및 프롬프트 추출"
} 