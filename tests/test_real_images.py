import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from PIL import Image
from nodes.image_prompt_extractor import ImagePromptExtractor
import numpy as np

def test_real_images():
    extractor = ImagePromptExtractor()
    
    # tests 폴더 기준으로 images 폴더 경로 설정
    current_dir = os.path.dirname(os.path.abspath(__file__))
    images_dir = os.path.join(current_dir, "images")
    
    print(f"이미지 디렉토리 경로: {images_dir}")
    
    if not os.path.exists(images_dir):
        print(f"'{images_dir}' 디렉토리를 찾을 수 없습니다.")
        return
        
    image_files = [f for f in os.listdir(images_dir) if f.endswith(('.png', '.jpg', '.jpeg'))]
    
    if not image_files:
        print(f"'{images_dir}' 디렉토리에 이미지 파일이 없습니다.")
        return
    
    print("\n=== ComfyUI 이미지 프롬프트 추출 결과 ===\n")
    
    for image_file in sorted(image_files):
        image_path = os.path.join(images_dir, image_file)
        print(f"\n📷 이미지 파일: {image_file}")
        
        try:
            # 이미지 로드
            img = Image.open(image_path)
            img_array = np.array(img)
            
            # 메타데이터 키 출력
            metadata = img.info
            print("\n🔍 메타데이터 키:")
            for key in metadata.keys():
                print(f"  - {key}")
            
            # 프롬프트 추출
            result = extractor.extract_prompt(img_array, image_path)
            
            print(f"\n📝 추출된 프롬프트 결과:")
            print(f"{result[0]}")
            print("-" * 80)
            
        except Exception as e:
            print(f"❌ 오류 발생: {str(e)}")
            print("-" * 80)

if __name__ == "__main__":
    test_real_images() 