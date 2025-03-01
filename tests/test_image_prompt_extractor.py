import unittest
import os
import json
import tempfile
import numpy as np
from PIL import Image
import PIL.PngImagePlugin
from nodes.image_prompt_extractor import ImagePromptExtractor

class TestImagePromptExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = ImagePromptExtractor()
        self.temp_dir = tempfile.mkdtemp()
        
        # 테스트용 이미지 생성
        self.test_image = np.zeros((64, 64, 3), dtype=np.uint8)
        self.image_path = os.path.join(self.temp_dir, "test_image.png")
        
        # 한글 프롬프트를 포함한 테스트 이미지 저장
        img = Image.fromarray(self.test_image)
        
        # 유니코드로 인코딩된 한글 프롬프트
        self.test_prompt = "\\uc544\\ub984\\ub2e4\\uc6b4 \\ud55c\\uad6d \\uc5ec\\uc131"
        self.expected_prompt = "아름다운 한국 여성"
        
        # PNG 메타데이터에 프롬프트 추가
        metadata = PngInfo()
        metadata.add_text("parameters", self.test_prompt)
        img.save(self.image_path, "PNG", pnginfo=metadata)

    def test_input_types(self):
        input_types = self.extractor.INPUT_TYPES()
        self.assertIn("required", input_types)
        self.assertIn("image", input_types["required"])
        self.assertIn("image_path", input_types["required"])

    def test_extract_prompt_success(self):
        result = self.extractor.extract_prompt(self.test_image, self.image_path)
        self.assertEqual(result[0], self.expected_prompt)

    def test_extract_prompt_no_metadata(self):
        # 메타데이터 없는 이미지 생성
        img = Image.fromarray(self.test_image)
        clean_image_path = os.path.join(self.temp_dir, "no_metadata.png")
        img.save(clean_image_path)
        
        result = self.extractor.extract_prompt(self.test_image, clean_image_path)
        self.assertEqual(result[0], "프롬프트를 찾을 수 없습니다.")

    def test_decode_unicode_escape(self):
        # 유니코드 디코딩 테스트
        encoded = "\\uc548\\ub155\\ud558\\uc138\\uc694"
        expected = "안녕하세요"
        decoded = self.extractor.decode_unicode_escape(encoded)
        self.assertEqual(decoded, expected)

    def tearDown(self):
        # 테스트 파일들 정리
        if os.path.exists(self.image_path):
            os.remove(self.image_path)
        os.rmdir(self.temp_dir)

if __name__ == '__main__':
    unittest.main() 