# image_utils.py
import base64
from PySide6.QtWidgets import QFileDialog
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QPixmap

class ImageHandler:
    @staticmethod
    def load_multiple_from_file(parent=None):
        file_paths, _ = QFileDialog.getOpenFileNames(parent, "选择图片（可多选）", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not file_paths: return [], []
        pixmaps = []
        b64_strs = []
        for path in file_paths:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                pixmaps.append(pixmap)
                b64_strs.append(ImageHandler.pixmap_to_base64(pixmap))
        return pixmaps, b64_strs

    @staticmethod
    def pixmap_to_base64(pixmap: QPixmap):
        if pixmap.isNull(): return None
        ba = QBuffer()
        ba.open(QIODevice.WriteOnly)
        pixmap.save(ba, "JPG")
        return base64.b64encode(ba.data().data()).decode('utf-8')

    @staticmethod
    def build_multimodal_content(text: str, images_b64: list):
        content = [{"type": "text", "text": text or "请分析这些图片。"}]
        for b64 in images_b64:
            if b64:
                content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        return content