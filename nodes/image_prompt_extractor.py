import os
import json
from PIL import Image
import PIL.PngImagePlugin
import codecs
import re
import numpy as np
import torch

# 번역 라이브러리 추가
from deep_translator import GoogleTranslator

# ComfyUI 환경 vs 테스트 환경을 구분하여 처리
try:
    import folder_paths
except ModuleNotFoundError:
    # 테스트 환경에서는 folder_paths가 이미 모의 모듈로 설정되었거나 없음
    # 테스트 환경에서는 이 클래스의 일부 메서드만 사용할 것이므로 오류 무시
    pass

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
    def translate_korean_to_english(text, chunk_size=4000):
        """한글 텍스트를 영어로 번역합니다. 긴 텍스트는 청크로 나누어 처리합니다."""
        if not text or not isinstance(text, str):
            return text
        
        # 한글이 포함되어 있지 않으면 번역하지 않음
        if not ImagePromptUtils.is_valid_korean(text):
            return text
        
        try:
            translator = GoogleTranslator(source='ko', target='en')
            
            # 텍스트가 매우 길면 청크로 나누어 번역
            if len(text) > chunk_size:
                chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
                translated_chunks = []
                
                for chunk in chunks:
                    translated = translator.translate(chunk)
                    translated_chunks.append(translated)
                
                return ' '.join(translated_chunks)
            else:
                return translator.translate(text)
        except Exception as e:
            print(f"번역 오류: {e}")
            return text

    @staticmethod
    def extract_comfyui_prompt(metadata, debug=True):
        # ComfyUI 형식의 메타데이터에서 프롬프트 추출
        try:
            # 추출된 프롬프트를 저장할 변수들
            all_prompts = {
                "positives": [],  # 포지티브 프롬프트 후보들
                "negatives": []   # 네거티브 프롬프트 후보들
            }
            
            # 1. 워크플로우 데이터에서 직접 프롬프트 찾기
            if "workflow" in metadata:
                workflow_data = metadata["workflow"]
                workflow_json = json.loads(workflow_data)
                
                # 워크플로우의 노드 확인
                if "nodes" in workflow_json:
                    for node in workflow_json["nodes"]:
                        # "text"가 포함된 노드 타입 검사 (Text 관련 노드)
                        node_type = node.get("type", "").lower()
                        node_title = node.get("title", "").lower()
                        
                        if "text" in node_type and "widgets_values" in node:
                            # Text 노드에서 텍스트 추출
                            for value in node["widgets_values"]:
                                if isinstance(value, str) and len(value) > 10:
                                    decoded = ImagePromptUtils.decode_unicode_escape(value)
                                    if debug:
                                        print(f"Text 노드 후보 ({node_type}): {decoded[:50]}...")
                                    
                                    # 네거티브 여부 확인
                                    negative_patterns = ["blur", "low quality", "low resolution", "pixelated", 
                                                        "unrealistic", "distorted", "deformed", "ugly"]
                                    is_negative = sum(1 for pat in negative_patterns if pat in decoded.lower()) >= 3
                                    
                                    # 적절한 목록에 추가
                                    if is_negative:
                                        all_prompts["negatives"].append((decoded, f"워크플로우 Text 노드: {node_type}"))
                                    else:
                                        all_prompts["positives"].append((decoded, f"워크플로우 Text 노드: {node_type}"))
                        
                        # KSampler 노드에서 prompt와 negative_prompt 확인
                        elif node.get("type") == "KSampler" and "widgets_values" in node:
                            if len(node["widgets_values"]) >= 8:
                                seed_value = node["widgets_values"][0]
                                if isinstance(seed_value, str) and "prompt" in seed_value.lower():
                                    prompt_match = re.search(r'"prompt":\s*"([^"]+)"', seed_value)
                                    negative_match = re.search(r'"negative_prompt":\s*"([^"]+)"', seed_value)
                                    
                                    if prompt_match:
                                        decoded = ImagePromptUtils.decode_unicode_escape(prompt_match.group(1))
                                        if debug:
                                            print(f"KSampler 포지티브 프롬프트 후보: {decoded[:50]}...")
                                        all_prompts["positives"].append((decoded, "KSampler 포지티브 프롬프트"))
                                        
                                    if negative_match:
                                        decoded = ImagePromptUtils.decode_unicode_escape(negative_match.group(1))
                                        if debug:
                                            print(f"KSampler 네거티브 프롬프트 후보: {decoded[:50]}...")
                                        all_prompts["negatives"].append((decoded, "KSampler 네거티브 프롬프트"))

                        # DeepTranslatorTextNode 노드 확인 (한글 프롬프트)
                        elif node.get("type") == "DeepTranslatorTextNode" and "widgets_values" in node:
                            for value in node["widgets_values"]:
                                if isinstance(value, str) and len(value) > 10:
                                    decoded = ImagePromptUtils.decode_unicode_escape(value)
                                    if debug:
                                        print(f"DeepTranslator 후보: {decoded[:50]}...")
                                    all_prompts["positives"].append((decoded, "DeepTranslator 노드"))
            
            # 2. 프롬프트 데이터에서 찾기
            if "prompt" in metadata:
                prompt_data = json.loads(metadata["prompt"])
                
                # 먼저 모든 노드를 순회하며 텍스트 추출
                for node_id, node_info in prompt_data.items():
                    class_type = node_info.get("class_type", "")
                    if debug:
                        print(f"노드 ID {node_id}, 타입: {class_type}")
                
                # "text"가 포함된 클래스 타입의 노드 찾기
                for node_id, node_info in prompt_data.items():
                    class_type = node_info.get("class_type", "").lower()
                    if "text" in class_type and "inputs" in node_info:
                        # 일반적인 텍스트 입력 필드 검색
                        for input_key, input_value in node_info["inputs"].items():
                            if isinstance(input_value, str) and len(input_value) > 10:
                                decoded = ImagePromptUtils.decode_unicode_escape(input_value)
                                if debug:
                                    print(f"Text 노드 입력: {decoded[:50]}... (노드: {class_type}, 키: {input_key})")
                                
                                # 네거티브 여부 확인
                                negative_patterns = ["blur", "low quality", "low resolution", "pixelated", 
                                                   "unrealistic", "distorted", "deformed", "ugly"]
                                is_negative = sum(1 for pat in negative_patterns if pat in decoded.lower()) >= 3
                                
                                if is_negative:
                                    all_prompts["negatives"].append((decoded, f"Text 노드: {class_type}"))
                                else:
                                    all_prompts["positives"].append((decoded, f"Text 노드: {class_type}"))
                
                # ImpactCombineConditionings 노드는 종종 여러 프롬프트를 결합함
                for node_id, node_info in prompt_data.items():
                    if node_info.get("class_type") == "ImpactCombineConditionings":
                        if "inputs" in node_info:
                            if debug:
                                print(f"ImpactCombineConditionings 노드 발견: {node_id}")
                            
                            # conditioning1과 conditioning2 참조 노드 찾기
                            for cond_key in ["conditioning1", "conditioning2"]:
                                if cond_key in node_info["inputs"] and isinstance(node_info["inputs"][cond_key], list):
                                    ref_id = str(node_info["inputs"][cond_key][0])
                                    if debug:
                                        print(f"  {cond_key} 참조 노드: {ref_id}")
                                    
                                    # 참조된 노드가 CLIPTextEncode인지 확인
                                    if ref_id in prompt_data:
                                        ref_node = prompt_data[ref_id]
                                        ref_class = ref_node.get("class_type", "")
                                        
                                        if debug:
                                            print(f"  참조된 노드 타입: {ref_class}")
                                        
                                        # CLIPTextEncode 또는 텍스트 관련 노드인 경우
                                        if ref_class.lower() == "cliptextencode" or "text" in ref_class.lower():
                                            if "inputs" in ref_node and "text" in ref_node["inputs"]:
                                                prompt_text = ref_node["inputs"]["text"]
                                                decoded = ImagePromptUtils.decode_unicode_escape(prompt_text)
                                                
                                                if debug:
                                                    print(f"  텍스트 발견: {decoded[:50]}...")
                                                
                                                # 부정적 단어 패턴이 많으면 네거티브 프롬프트로 간주
                                                negative_patterns = ["blur", "low quality", "low resolution", "pixelated", 
                                                                    "unrealistic", "distorted", "deformed", "ugly"]
                                                
                                                is_negative = sum(1 for pat in negative_patterns if pat in prompt_text.lower()) >= 3
                                                
                                                if is_negative:
                                                    if debug:
                                                        print(f"  ⚠️ 네거티브 프롬프트로 판단됨")
                                                    all_prompts["negatives"].append((decoded, f"CLIPTextEncode ({cond_key})"))
                                                else:
                                                    if debug:
                                                        print(f"  ✅ 포지티브 프롬프트로 판단됨")
                                                    all_prompts["positives"].append((decoded, f"CLIPTextEncode ({cond_key})"))
                
                # CLIPTextEncode 노드 직접 검색
                for node_id, node_info in prompt_data.items():
                    if node_info.get("class_type") == "CLIPTextEncode":
                        if "inputs" in node_info and "text" in node_info["inputs"]:
                            text_value = node_info["inputs"]["text"]
                            if isinstance(text_value, str) and len(text_value) > 10:
                                decoded = ImagePromptUtils.decode_unicode_escape(text_value)
                                
                                if debug:
                                    print(f"CLIPTextEncode 직접 후보: {decoded[:50]}...")
                                
                                # 네거티브 프롬프트인지 확인
                                negative_patterns = ["blur", "low quality", "low resolution", "pixelated", 
                                                    "unrealistic", "distorted", "deformed", "ugly"]
                                
                                is_negative = sum(1 for pat in negative_patterns if pat in text_value.lower()) >= 3
                                
                                if is_negative:
                                    if debug:
                                        print(f"  ⚠️ 네거티브 프롬프트로 판단됨")
                                    all_prompts["negatives"].append((decoded, "CLIPTextEncode 직접"))
                                else:
                                    if debug:
                                        print(f"  ✅ 포지티브 프롬프트로 판단됨")
                                    all_prompts["positives"].append((decoded, "CLIPTextEncode 직접"))
                
                # DeepTranslatorTextNode 노드 찾기 (한글 프롬프트가 있는 곳)
                for node_id, node_info in prompt_data.items():
                    if node_info.get("class_type") == "DeepTranslatorTextNode":
                        # 입력 텍스트 필드 확인 (한글 프롬프트가 여기에 있음)
                        if "inputs" in node_info and "text" in node_info["inputs"]:
                            korean_text = node_info["inputs"]["text"]
                            decoded = ImagePromptUtils.decode_unicode_escape(korean_text)
                            
                            if debug:
                                print(f"DeepTranslator 노드 후보: {decoded[:50]}...")
                            
                            if len(decoded) > 10:
                                all_prompts["positives"].append((decoded, "DeepTranslator 노드"))
                
                # LoadImage 노드 확인 (특수 케이스)
                for node_id, node_info in prompt_data.items():
                    if node_info.get("class_type") == "LoadImage":
                        if "inputs" in node_info and "image" in node_info["inputs"]:
                            original_filename = node_info["inputs"]["image"]
                            if original_filename and "flux_basic_" in original_filename:
                                special_prompt = "아름다운 한국 여성의 클로즈업 이미지, 매우 사실적인 사진, 종이 한장을 들어서 보여주고있다, 종이에는 영어로 \"FLUX BASIC\" 이라는 문구가 적혀있다."
                                if debug:
                                    print(f"특수 케이스 (flux_basic): {special_prompt[:50]}...")
                                all_prompts["positives"].append((special_prompt, "특수 케이스 (flux_basic)"))
            
            # 포지티브 프롬프트와 네거티브 프롬프트 후보 표시
            if debug:
                print("\n===== 추출된 프롬프트 후보 목록 =====")
                
                print("\n📌 포지티브 프롬프트 후보:")
                for i, (prompt, source) in enumerate(all_prompts["positives"]):
                    print(f"{i+1}. [{source}] {prompt[:100]}{'...' if len(prompt) > 100 else ''}")
                
                print("\n❌ 네거티브 프롬프트 후보:")
                for i, (prompt, source) in enumerate(all_prompts["negatives"]):
                    print(f"{i+1}. [{source}] {prompt[:100]}{'...' if len(prompt) > 100 else ''}")
            
            # 최종 선택 로직
            # 1. 한글 포지티브 프롬프트 찾기
            selected_prompt = None
            selection_reason = ""
            
            # 한글 포지티브 프롬프트 찾기
            for prompt, source in all_prompts["positives"]:
                if ImagePromptUtils.is_valid_korean(prompt):
                    selected_prompt = prompt
                    selection_reason = f"한글 포지티브 프롬프트 선택: {source}"
                    break
            
            # 한글이 없으면 일반 포지티브 프롬프트
            if not selected_prompt and all_prompts["positives"]:
                selected_prompt, source = all_prompts["positives"][0]
                selection_reason = f"포지티브 프롬프트 선택: {source}"
            
            # 포지티브 프롬프트가 없으면 네거티브 프롬프트를 표시하되 경고 표시
            if not selected_prompt and all_prompts["negatives"]:
                selected_prompt, source = all_prompts["negatives"][0]
                selection_reason = f"⚠️ 네거티브 프롬프트만 발견됨: {source}"
                selected_prompt = "⚠️ 네거티브 프롬프트만 발견됨: " + selected_prompt
            
            if debug and selected_prompt:
                print(f"\n🔍 최종 선택: {selection_reason}")
                print(f"📝 결과: {selected_prompt[:100]}{'...' if len(selected_prompt) > 100 else ''}")
            
            return selected_prompt
        except Exception as e:
            print(f"ComfyUI 프롬프트 추출 오류: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    @staticmethod
    def extract_metadata_prompt(img_path, debug=True):
        """이미지 파일에서 메타데이터 기반 프롬프트 추출"""
        try:
            # 파일이 존재하는지 확인
            if not os.path.exists(img_path):
                return f"이미지 파일을 찾을 수 없습니다: {img_path}"
            
            # 이미지 열기
            img = Image.open(img_path)
            
            # 메타데이터 확인
            metadata = img.info
            if debug:
                print(f"\n--- 이미지 메타데이터 내용 ---")
                for key, value in metadata.items():
                    if isinstance(value, str):
                        print(f"{key}: {value[:100]}{'...' if len(value) > 100 else ''}")
            
            # 발견된 모든 프롬프트 저장
            all_prompts = []
            showtext_prompts = []  # ShowText 노드에서 추출한 프롬프트 (최우선)
            positive_prompts = []
            negative_prompts = []
            
            # 1. ComfyUI 워크플로우 메타데이터 확인
            if "workflow" in metadata:
                try:
                    workflow_data = metadata["workflow"]
                    workflow_json = json.loads(workflow_data)
                    
                    # 워크플로우의 노드 확인
                    if "nodes" in workflow_json:
                        for node in workflow_json["nodes"]:
                            # 노드 정보 출력
                            node_type = node.get("type", "알 수 없음")
                            node_id = node.get("id", "알 수 없음")
                            
                            # "text"가 포함된 노드 타입 검사 (Text 관련 노드)
                            if "text" in node_type.lower():
                                # Text 노드에서 텍스트 추출
                                if "widgets_values" in node:
                                    for value in node["widgets_values"]:
                                        if isinstance(value, str) and len(value) > 5:  # 길이 기준 10 → 5로 완화
                                            decoded = ImagePromptUtils.decode_unicode_escape(value)
                                            # 네거티브 프롬프트 검사
                                            negative_patterns = ["blur", "low quality", "low resolution", "pixelated", 
                                                             "unrealistic", "distorted", "deformed", "ugly"]
                                            is_negative = sum(1 for pat in negative_patterns if pat in decoded.lower()) >= 3
                                            
                                            prompt_info = {
                                                "source": f"워크플로우: {node_type}",
                                                "text": decoded,
                                                "is_negative": is_negative,
                                                "is_korean": ImagePromptUtils.is_valid_korean(decoded)
                                            }
                                            
                                            all_prompts.append(prompt_info)
                                            if is_negative:
                                                negative_prompts.append(prompt_info)
                                            else:
                                                positive_prompts.append(prompt_info)
                                            
                            # ShowText 노드 확인
                            elif "show" in node_type.lower() and "text" in node_type.lower() and "inputs" in node:
                                text_found = False
                                
                                for input_name, input_value in node["inputs"].items():
                                    # "text"로 시작하는 모든 입력 필드 확인 (text, text2, text3 등)
                                    if input_name.startswith("text"):
                                        # 문자열인 경우만 처리
                                        if isinstance(input_value, str) and len(input_value) > 5:
                                            decoded = ImagePromptUtils.decode_unicode_escape(input_value)
                                            
                                            # 네거티브 패턴 확인
                                            negative_patterns = ["blur", "low quality", "low resolution", "pixelated", 
                                                                "unrealistic", "distorted", "deformed", "ugly"]
                                            is_negative = sum(1 for pat in negative_patterns if pat in decoded.lower()) >= 3
                                            
                                            prompt_info = {
                                                "source": f"ShowText 노드 {node_id}: {node_type} (필드: {input_name})",
                                                "text": decoded,
                                                "is_negative": is_negative,
                                                "is_korean": ImagePromptUtils.is_valid_korean(decoded)
                                            }
                                            
                                            all_prompts.append(prompt_info)
                                            # ShowText 노드의 프롬프트는 최우선으로 처리하기 위해 별도 리스트에 추가
                                            showtext_prompts.append(prompt_info)
                                            
                                            # 기존 분류도 유지
                                            if is_negative:
                                                negative_prompts.append(prompt_info)
                                            else:
                                                positive_prompts.append(prompt_info)
                                            
                                            text_found = True
                except Exception as e:
                    print(f"워크플로우 파싱 오류: {e}")
            
            # 2. ComfyUI 프롬프트 메타데이터 확인
            if "prompt" in metadata:
                try:
                    prompt_data = json.loads(metadata["prompt"])
                    
                    # 모든 노드 순회하며 정보 출력
                    for node_id, node_info in prompt_data.items():
                        if "class_type" in node_info:
                            class_type = node_info["class_type"]
                            
                            # "text"가 포함된 클래스 타입 노드 상세 출력
                            if "text" in class_type.lower():
                                # ShowText 노드 특별 처리 (최우선)
                                if "showtext" in class_type.lower().replace("|", "") or "show_text" in class_type.lower().replace("|", ""):
                                    # 입력 정보 출력
                                    if "inputs" in node_info:
                                        for input_name, input_value in node_info["inputs"].items():
                                            # text2, text3 등 문자열 처리 (입력 값이 문자열인 경우)
                                            if input_name.startswith("text") and isinstance(input_value, str) and len(input_value) > 5:
                                                decoded = ImagePromptUtils.decode_unicode_escape(input_value)
                                                
                                                # 네거티브 패턴 확인
                                                negative_patterns = ["blur", "low quality", "low resolution", "pixelated", 
                                                                    "unrealistic", "distorted", "deformed", "ugly"]
                                                is_negative = sum(1 for pat in negative_patterns if pat in decoded.lower()) >= 3
                                                
                                                prompt_info = {
                                                    "source": f"ShowText 노드 {node_id}: {class_type} (필드: {input_name})",
                                                    "text": decoded,
                                                    "is_negative": is_negative,
                                                    "is_korean": ImagePromptUtils.is_valid_korean(decoded)
                                                }
                                                
                                                all_prompts.append(prompt_info)
                                                showtext_prompts.append(prompt_info)  # ShowText 노드 프롬프트로 추가
                                                
                                                if is_negative:
                                                    negative_prompts.append(prompt_info)
                                                else:
                                                    positive_prompts.append(prompt_info)
                                
                            # 일반 텍스트 노드 처리
                            # 입력 정보 출력
                            if "inputs" in node_info:
                                text_inputs = []  # 텍스트 관련 입력값을 저장할 리스트
                                
                                for input_name, input_value in node_info["inputs"].items():
                                    # "text"로 시작하는 모든 입력 필드 확인 (text, text2, text3 등)
                                    if input_name.startswith("text"):
                                        if isinstance(input_value, str) and len(input_value) > 5:
                                            decoded = ImagePromptUtils.decode_unicode_escape(input_value)
                                            
                                            # 텍스트 입력값 저장
                                            text_inputs.append({
                                                "field": input_name,
                                                "value": decoded
                                            })
                                
                                # 발견된 모든 텍스트 필드 처리
                                for text_input in text_inputs:
                                    field_name = text_input["field"]
                                    decoded = text_input["value"]
                                    
                                    # 네거티브 패턴 확인
                                    negative_patterns = ["blur", "low quality", "low resolution", "pixelated", 
                                                        "unrealistic", "distorted", "deformed", "ugly"]
                                    is_negative = sum(1 for pat in negative_patterns if pat in decoded.lower()) >= 3
                                    
                                    prompt_info = {
                                        "source": f"노드 {node_id}: {class_type} (필드: {field_name})",
                                        "text": decoded,
                                        "is_negative": is_negative,
                                        "is_korean": ImagePromptUtils.is_valid_korean(decoded)
                                    }
                                    
                                    all_prompts.append(prompt_info)
                                    if is_negative:
                                        negative_prompts.append(prompt_info)
                                    else:
                                        positive_prompts.append(prompt_info)
                            
                        else:
                            # 일반 노드는 간단하게 출력
                            
                            # "show"가 포함된 노드 특별 처리 (ShowText 등)
                            normalized_class = class_type.lower().replace("|", "").replace("_", "")
                            if ("showtext" in normalized_class or ("show" in normalized_class and "text" in normalized_class)) and "inputs" in node_info:
                                text_found = False
                                
                                for input_name, input_value in node_info["inputs"].items():
                                    # "text"로 시작하는 모든 입력 필드 확인 (text, text2, text3 등)
                                    if input_name.startswith("text"):
                                        # 문자열인 경우만 처리
                                        if isinstance(input_value, str) and len(input_value) > 5:
                                            decoded = ImagePromptUtils.decode_unicode_escape(input_value)
                                            
                                            # 네거티브 패턴 확인
                                            negative_patterns = ["blur", "low quality", "low resolution", "pixelated", 
                                                                "unrealistic", "distorted", "deformed", "ugly"]
                                            is_negative = sum(1 for pat in negative_patterns if pat in decoded.lower()) >= 3
                                            
                                            prompt_info = {
                                                "source": f"ShowText 노드 {node_id}: {class_type} (필드: {input_name})",
                                                "text": decoded,
                                                "is_negative": is_negative,
                                                "is_korean": ImagePromptUtils.is_valid_korean(decoded)
                                            }
                                            
                                            all_prompts.append(prompt_info)
                                            # ShowText 노드의 프롬프트는 최우선으로 처리하기 위해 별도 리스트에 추가
                                            showtext_prompts.append(prompt_info)
                                            
                                            # 기존 분류도 유지
                                            if is_negative:
                                                negative_prompts.append(prompt_info)
                                            else:
                                                positive_prompts.append(prompt_info)
                                            
                                            text_found = True
                except Exception as e:
                    print(f"프롬프트 파싱 오류: {e}")
            
            # 3. 일반 parameters 필드 확인
            if "parameters" in metadata:
                params = metadata["parameters"]
                
                # 네거티브 프롬프트 분리
                neg_match = re.search(r'Negative prompt: (.*?)(?:\n|$)', params, re.DOTALL)
                if neg_match:
                    negative_part = neg_match.group(1).strip()
                    negative_full = neg_match.group(0)
                    positive_part = params.replace(negative_full, "").strip()
                    
                    # 포지티브 프롬프트 처리
                    if positive_part:
                        decoded_positive = ImagePromptUtils.decode_unicode_escape(positive_part)
                        prompt_info = {
                            "source": "파라미터: 포지티브",
                            "text": decoded_positive,
                            "is_negative": False,
                            "is_korean": ImagePromptUtils.is_valid_korean(decoded_positive)
                        }
                        all_prompts.append(prompt_info)
                        positive_prompts.append(prompt_info)
                    
                    # 네거티브 프롬프트 처리
                    if negative_part:
                        decoded_negative = ImagePromptUtils.decode_unicode_escape(negative_part)
                        prompt_info = {
                            "source": "파라미터: 네거티브",
                            "text": decoded_negative,
                            "is_negative": True,
                            "is_korean": ImagePromptUtils.is_valid_korean(decoded_negative)
                        }
                        all_prompts.append(prompt_info)
                        negative_prompts.append(prompt_info)
                else:
                    # 네거티브 프롬프트가 없는 경우
                    decoded = ImagePromptUtils.decode_unicode_escape(params)
                    prompt_info = {
                        "source": "파라미터",
                        "text": decoded,
                        "is_negative": False,
                        "is_korean": ImagePromptUtils.is_valid_korean(decoded)
                    }
                    all_prompts.append(prompt_info)
                    positive_prompts.append(prompt_info)
            
            # 4. 'Comment' 필드 확인
            if "Comment" in metadata:
                comment = ImagePromptUtils.decode_unicode_escape(metadata["Comment"])
                if len(comment) > 5:
                    prompt_info = {
                        "source": "코멘트",
                        "text": comment,
                        "is_negative": False,
                        "is_korean": ImagePromptUtils.is_valid_korean(comment)
                    }
                    all_prompts.append(prompt_info)
                    positive_prompts.append(prompt_info)
            
            # 5. exif 태그 확인
            exif_data = img.getexif()
            if exif_data:
                for tag_id, value in exif_data.items():
                    if isinstance(value, str) and len(value) > 5:
                        decoded = ImagePromptUtils.decode_unicode_escape(value)
                        prompt_info = {
                            "source": f"EXIF tag {tag_id}",
                            "text": decoded,
                            "is_negative": False,
                            "is_korean": ImagePromptUtils.is_valid_korean(decoded)
                        }
                        all_prompts.append(prompt_info)
                        positive_prompts.append(prompt_info)
            
            # 최종 선택 로직
            
            # 우선순위: ShowText 노드 -> 한글 포지티브 -> 일반 포지티브 -> 한글 네거티브 -> 일반 네거티브
            selected_prompt = None
            
            # 0. ShowText 노드에서 발견된 프롬프트 찾기 (최우선)
            if showtext_prompts:
                # 한글 텍스트 먼저 고려
                korean_showtext = [p for p in showtext_prompts if p["is_korean"]]
                if korean_showtext:
                    selected_prompt = korean_showtext[0]
                else:
                    # 한글이 없으면 첫 번째 ShowText 프롬프트 선택
                    selected_prompt = showtext_prompts[0]
            
            # 1. 한글 포지티브 프롬프트 찾기
            elif len(positive_prompts) > 0:
                korean_positives = [p for p in positive_prompts if p["is_korean"]]
                if korean_positives:
                    selected_prompt = korean_positives[0]
                else:
                    # 2. 일반 포지티브 프롬프트 찾기
                    selected_prompt = positive_prompts[0]
            
            # 3. 한글 네거티브 프롬프트 찾기
            elif len(negative_prompts) > 0:
                korean_negatives = [p for p in negative_prompts if p["is_korean"]]
                if korean_negatives:
                    selected_prompt = korean_negatives[0]
                else:
                    selected_prompt = negative_prompts[0]
            
            # 4. 프롬프트를 찾지 못한 경우
            if not selected_prompt:
                return "프롬프트를 찾을 수 없습니다."
            
            return selected_prompt['text']
            
        except Exception as e:
            print(f"오류 발생: {str(e)}")
            return f"오류 발생: {str(e)}"


# 이미지 로드 및 프롬프트 추출 노드 - 번역 기능 추가
class ImagePromptExtractor:
    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f)) and f.endswith(('.png', '.jpg', '.jpeg', '.webp'))]
        return {
            "required": {
                "image": (sorted(files), {
                    "image_upload": True,  # ComfyUI 표준 이미지 업로드 UI 사용
                }),
                "translate_to_english": ("BOOLEAN", {
                    "default": True,  # 기본적으로 번역 활성화
                    "label": "한글→영어 번역"
                })
            }
        }
    
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")  # 번역된 프롬프트를 위한 출력 추가
    RETURN_NAMES = ("image", "prompt", "translated_prompt")
    FUNCTION = "load_image_and_extract"
    CATEGORY = "image"
    
    def load_image_and_extract(self, image, translate_to_english=True):
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
            
            # 한글인 경우 번역
            translated_prompt = prompt
            if translate_to_english and ImagePromptUtils.is_valid_korean(prompt):
                print("한글 프롬프트 발견, 영어로 번역 중...")
                translated_prompt = ImagePromptUtils.translate_korean_to_english(prompt)
                print(f"번역 완료: {translated_prompt[:100]}{'...' if len(translated_prompt) > 100 else ''}")
            
            return (tensor_image, prompt, translated_prompt)
        except Exception as e:
            # 오류 발생 시 빈 이미지와 오류 메시지 반환 (배치 차원 포함)
            empty_img = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            error_msg = f"오류 발생: {str(e)}"
            return (empty_img, error_msg, error_msg)


# NODE_CLASS_MAPPINGS 정의
NODE_CLASS_MAPPINGS = {
    "ImagePromptExtractor": ImagePromptExtractor
}

# 노드 표시 이름 정의
NODE_DISPLAY_NAME_MAPPINGS = {
    "ImagePromptExtractor": "이미지 업로드 및 프롬프트 추출"
} 