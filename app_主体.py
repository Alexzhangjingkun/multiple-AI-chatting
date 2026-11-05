# app_主体.py
import os
import sys
import re
import json
import traceback
import httpx
from datetime import datetime

os.environ["PYTHONUTF8"] = "1"

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy,
    QPushButton, QSplitter, QLabel, QMessageBox, QTextEdit, QTabWidget, QScrollArea
)
from PySide6.QtCore import QThread, Signal, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QGuiApplication, QPixmap
from PySide6.QtWebEngineWidgets import QWebEngineView

from openai import OpenAI
from thinking_ui import HTML_TEMPLATE, ThinkingController, VerificationTab
from image_utils import ImageHandler

# ============================================== 配置 ==============================================
MAIN_BASE_URL = "https://api.deepseek.com/v1"
MAIN_API_KEY = "？？？？？"
MAIN_MODEL = "deepseek-flash"

DENO_BASE_URL = "https://openai-gemini.alexzhangjingkun.deno.net/v1"
DENO_API_KEY = "？？？？？" 
GEMINI_MODEL = "gemini-3.6-flash"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_API_KEY = "？？？？？" 

OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_API_KEY = "ollama" 

CLOUD_VERIFIERS = {
    "Gemini 3.6 (Cloud)": {"url": DENO_BASE_URL, "key": DENO_API_KEY, "model": GEMINI_MODEL, "high_priority": True},
    "Nemotron 3 (Cloud)": {"url": OPENROUTER_BASE_URL, "key": OPENROUTER_API_KEY, "model": "nvidia/nemotron-3-ultra-550b-a55b:free"},
    "随机模型 1 (Cloud)": {"url": OPENROUTER_BASE_URL, "key": OPENROUTER_API_KEY, "model": "openrouter/free"},
    "随机模型 2 (Cloud)": {"url": OPENROUTER_BASE_URL, "key": OPENROUTER_API_KEY, "model": "openrouter/free"},
}
LOCAL_VERIFIERS = {
    "Qwen 2.5 3B (Local)": {"url": OLLAMA_BASE_URL, "key": OLLAMA_API_KEY, "model": "qwen2.5:3b"}
}
ALL_VERIFIERS = {**CLOUD_VERIFIERS, **LOCAL_VERIFIERS}
# ==============================================================================================================

TODAY_STR = datetime.now().strftime("%Y年%m月%d日")

DETAIL_PROMPT = f"""你是一个元核查专家。下面是多个独立 AI 模型对同一个回答的验证报告。
请综合这些报告，完成以下任务：
1. **提取共识**：多个模型都认为正确或都认为错误的内容。
2. **指出分歧**：列出模型之间存在矛盾的声明，并分析哪一方更可信。
3. **时效性审查**：如果验证报告中指出主回答包含过时的信息，请作为重点指出。
4. **综合可信度**：给出一个综合的可信度评分（0-100%）。
5. **最终结论**：给出 TRUSTWORTHY / NEEDS_CAUTION / UNRELIABLE 之一。

【 特别注意 】：
- 如果某份报告的内容仅为 `[该模型未启用]`、`[该模型因网络、额度或限流原因未能提供有效意见]`，或者**明显话没说完（被截断）**，请**直接忽略该报告**。
- 在“Gemini 3.6 (Cloud)”的有效审查报告中，如果它指出了任何具体的错误或遗漏，**请赋予该意见较高的权重**。

【原始问题】
{{question}}
【主回答】
{{answer}}
【验证报告汇总】
{{reports}}

请严格按结构输出，并在最后输出：[CONFIDENCE: XX%]"""

BRIEF_PROMPT = f"""你是一个元核查专家。下面是多个独立 AI 模型对同一个回答的验证报告。
请直接给出一个**极简版**的综合结论：
1. 核心共识：哪些是对的，哪些是错的（一两句话）。
2. 关键分歧：如果各模型吵得不可开交，指出最大的争议点。
3. 综合置信度评分（0-100%）。
4. 最终结论（TRUSTWORTHY / NEEDS_CAUTION / UNRELIABLE）。

请直接输出这四点，不要长篇大论。并在最后输出：[CONFIDENCE: XX%]

【原始问题】
{{question}}
【主回答】
{{answer}}
【验证报告汇总】
{{reports}}"""

def build_verification_prompt(question: str, answer: str, is_local: bool, has_image: bool) -> str:
    image_note = "【注意】：用户随问题提供了一张或多张图片，请结合图片内容进行验证。" if has_image else ""
    if is_local:
        return f"""你是一个严谨的审查员。{image_note}
【注意】：不要自己重新解题！你的任务是审查下面给出的回答。
请顺着回答的步骤阅读，检查是否有明显的计算错误或逻辑漏洞，给出简短意见即可。
回答最后请给出 [CONFIDENCE: XX%]

问题：{question}
回答：{answer}"""
    else:
        return f"""今天是 {TODAY_STR}。你是一个严格、公正的事实核查编辑。{image_note}
【 注意事项 】：你的任务是**审查和批改**下方已经生成的回答。**而不是自己从头重新解题**。
请顺着回答的推导步骤阅读，检查：
1. 公式和计算是否有误？
2. 逻辑推导是否严密？
3. 是否有遗漏或过时信息？
如果发现错误，请直接指出在哪一步出了错；如果全对，请说明它的步骤是完备的。

【原始问题】
{question}
【待审查的回答】
{answer}

请使用标准的 Markdown 语法。如果涉及数学公式，请严格使用 LaTeX 语法。
请在审查意见最后输出：[CONFIDENCE: XX%]"""

class StreamWorker(QThread):
    chunk = Signal(str)
    done = Signal(str)
    error = Signal(str)
    actual_model = Signal(str) 

    def __init__(self, base_url, api_key, model_id, messages, use_proxy=True):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model_id = model_id
        self.messages = messages
        self.use_proxy = use_proxy
        self._full = ""
        self._model_sent = False

    def run(self):
        try:
            http_client = httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), trust_env=self.use_proxy)
            client = OpenAI(api_key=self.api_key, base_url=self.base_url, http_client=http_client)
            stream = client.chat.completions.create(model=self.model_id, messages=self.messages, stream=True)

            for chunk in stream:
                if not self._model_sent and getattr(chunk, "model", None):
                    self.actual_model.emit(chunk.model)
                    self._model_sent = True
                if not chunk.choices: continue
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None) or ""
                if content:
                    self._full += content
                    self.chunk.emit(content)
            self.done.emit(self._full)
        except Exception as e:
            self.error.emit(traceback.format_exc())

class ChatInput(QTextEdit):
    send_requested = Signal()
    image_pasted = Signal(QPixmap)
    
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier: super().keyPressEvent(event)
            else: self.send_requested.emit()
            return
        super().keyPressEvent(event)
        
    def insertFromMimeData(self, source):
        try:
            clipboard = QGuiApplication.clipboard()
            if clipboard and clipboard.mimeData() and clipboard.mimeData().hasImage():
                img = clipboard.image()
                if not img.isNull():
                    self.image_pasted.emit(QPixmap.fromImage(img))
                    return
                    
            if source.hasUrls():
                for url in source.urls():
                    if url.isLocalFile():
                        path = url.toLocalFile()
                        if path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp')):
                            pixmap = QPixmap(path)
                            if not pixmap.isNull():
                                self.image_pasted.emit(pixmap)
                return
        except Exception as e:
            print(f"读取剪贴板失败: {e}")
            
        super().insertFromMimeData(source)

class ImagePreviewWidget(QWidget):
    deleted = Signal(str)
    def __init__(self, pixmap, b64):
        super().__init__()
        self.b64 = b64
        self.setFixedSize(80, 80)
        
        label = QLabel(self)
        label.setFixedSize(80, 80)
        label.setStyleSheet("border: 1px solid #ddd; border-radius: 4px;")
        label.setScaledContents(True)
        label.setPixmap(pixmap)
        
        btn = QPushButton("❌", self)
        btn.setFixedSize(18, 18)
        btn.move(62, 0)
        btn.setStyleSheet("background-color: #d73a49; color: white; border-radius: 9px; padding: 0; font-size: 10px; font-weight: bold; border: none;")
        btn.raise_()
        btn.clicked.connect(self.delete_self)
        
    def delete_self(self):
        self.deleted.emit(self.b64)
        self.deleteLater()

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        #---------------------标题---------------------
        self.setWindowTitle("多模态审查系统")
        self.resize(1500, 950)
        
        self.setStyleSheet("""
            QWidget { font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; font-size: 14px; }
            QTabWidget::pane { border: 1px solid #ddd; background: #fff; }
            QTabBar::tab { background: #f0f0f0; padding: 8px 16px; border: 1px solid #ddd; border-bottom: none; margin-right: 2px; }
            QTabBar::tab:selected { background: #fff; font-weight: bold; color: #0366d6; }
            QTextEdit { border: 1px solid #ccc; border-radius: 4px; padding: 6px; }
            QPushButton { background: #0366d6; color: white; border: none; border-radius: 4px; padding: 8px 16px; font-weight: bold; }
            QPushButton:hover { background: #005cc5; }
            QPushButton:disabled { background: #a0a0a0; }
        """)

        self.active_workers = []
        self.finished_reports = {}
        self.main_answer = ""
        self.chat_history = []
        
        self.images_b64 = []
        self.image_widgets = []
        
        self.dirty_tabs = set()
        self.extracted_text = ""
        self.raw_main_buffer = ""
        self.is_main_ocr_done = False
        
        self.stage = "idle"  
        self.agg_mode = "detail"
        self.agg_worker = None

        self.render_timer = QTimer(self)
        self.render_timer.timeout.connect(self.update_webviews)
        self.render_timer.start(200)

        root = QVBoxLayout(self)
        self.splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.history_label = QLabel("当前提问：（暂无）")
        self.history_label.setStyleSheet("color: #444; background: #eef2f5; padding: 12px; border-radius: 6px; font-weight: bold;")
        left_layout.addWidget(self.history_label)
        
        title_layout = QHBoxLayout()
        title_layout.addWidget(QLabel(f"主回答：{MAIN_MODEL}"))
        title_layout.addStretch()
        left_layout.addLayout(title_layout)
        
        self.answer_view = QWebEngineView()
        self.answer_view.setHtml(HTML_TEMPLATE)
        left_layout.addWidget(self.answer_view)
        self.answer_buffer = ""

        self.tab_widget = QTabWidget()
        self.tab_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.verify_tabs = {}
        
        for name, cfg in ALL_VERIFIERS.items():
            is_local = "Local" in name
            tab = VerificationTab(f"{name} ({cfg['model']})", is_local=is_local)
            if is_local:
                tab.enable_clicked.connect(self._start_local_verifiers)
            self.verify_tabs[name] = tab
            self.tab_widget.addTab(tab, name)
            
        self.ocr_tab = VerificationTab("图片提取原文")
        
        self.aggregator_tab = VerificationTab("综合结论")
        ThinkingController.waiting(self.aggregator_tab.view)
        
        agg_container = QWidget()
        agg_layout = QVBoxLayout(agg_container)
        agg_layout.setContentsMargins(0, 0, 0, 0)
        
        btn_layout = QHBoxLayout()
        self.btn_detail = QPushButton(" 详细版")
        self.btn_brief = QPushButton(" 简略版")
        
        self.btn_detail.setStyleSheet("background-color: #005cc5; color: white; padding: 8px 16px; font-weight: bold;")
        self.btn_brief.setStyleSheet("background-color: #f6f8fa; color: #24292e; border: 1px solid #d1d5da; padding: 8px 16px;")
        
        self.btn_detail.clicked.connect(lambda: self._request_aggregation("detail"))
        self.btn_brief.clicked.connect(lambda: self._request_aggregation("brief"))
        
        btn_layout.addWidget(self.btn_detail)
        btn_layout.addWidget(self.btn_brief)
        btn_layout.addStretch()
        agg_layout.addLayout(btn_layout)
        agg_layout.addWidget(self.aggregator_tab)
        
        self.tab_widget.addTab(agg_container, "综合结论")

        self.splitter.addWidget(left)
        self.splitter.addWidget(self.tab_widget)
        
        self.splitter.setSizes([750, 750])
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        
        root.addWidget(self.splitter, stretch=1)

        input_container = QVBoxLayout()
        
        self.image_scroll = QScrollArea()
        self.image_scroll.setFixedHeight(100)
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.image_container = QWidget()
        self.image_layout = QHBoxLayout(self.image_container)
        self.image_layout.setContentsMargins(0, 0, 0, 0)
        self.image_layout.setSpacing(10)
        self.image_layout.addStretch()
        self.image_scroll.setWidget(self.image_container)
        self.image_scroll.hide()
        input_container.addWidget(self.image_scroll)

        input_row = QHBoxLayout()
        self.upload_btn = QPushButton("导入图片")
        self.upload_btn.setFixedWidth(80)
        self.upload_btn.setStyleSheet("background-color: #f6f8fa; color: #24292e; border: 1px solid #d1d5da;")
        self.upload_btn.clicked.connect(self.select_image)
        
        self.clear_mem_btn = QPushButton("清空")
        self.clear_mem_btn.setFixedWidth(80)
        self.clear_mem_btn.setStyleSheet("background-color: #f6f8fa; color: #24292e; border: 1px solid #d1d5da;")
        self.clear_mem_btn.clicked.connect(self.clear_memory)
        
        self.input_edit = ChatInput()
        self.input_edit.setFixedHeight(60)
        self.input_edit.send_requested.connect(self.on_send)
        self.input_edit.image_pasted.connect(self.handle_pasted_image)
        
        self.send_btn = QPushButton("发送")
        self.send_btn.setFixedWidth(80)
        self.send_btn.clicked.connect(self.on_send)
        
        input_row.addWidget(self.upload_btn)
        input_row.addWidget(self.clear_mem_btn)
        input_row.addWidget(self.input_edit, stretch=1)
        input_row.addWidget(self.send_btn)
        input_container.addLayout(input_row)
        root.addLayout(input_container)
        
        self.status = QLabel("就绪")
        self.status.setStyleSheet("color: #666; padding: 4px;")
        root.addWidget(self.status)

    def clear_memory(self):
        self.chat_history.clear()
        self.history_label.setText("当前提问：（记忆已清空）")

    def select_image(self):
        pixmaps, b64_strs = ImageHandler.load_multiple_from_file(self)
        for pixmap, b64 in zip(pixmaps, b64_strs):
            self.display_image(pixmap, b64)

    def handle_pasted_image(self, pixmap):
        b64_str = ImageHandler.pixmap_to_base64(pixmap)
        if b64_str: self.display_image(pixmap, b64_str)

    def display_image(self, pixmap, b64_str):
        if b64_str in self.images_b64: return 
        
        self.images_b64.append(b64_str)
        self.image_scroll.show()
        
        widget = ImagePreviewWidget(pixmap, b64_str)
        widget.deleted.connect(self.remove_image)
        self.image_widgets.append(widget)
        
        self.image_layout.insertWidget(self.image_layout.count() - 1, widget)

    def remove_image(self, b64_str):
        if b64_str in self.images_b64:
            self.images_b64.remove(b64_str)
        
        for w in self.image_widgets:
            if w.b64 == b64_str:
                self.image_widgets.remove(w)
                break
                
        if not self.images_b64:
            self.image_scroll.hide()

    def clear_image(self):
        self.images_b64.clear()
        for widget in self.image_widgets:
            widget.deleteLater()
        self.image_widgets.clear()
        self.image_scroll.hide()

    def update_webviews(self):
        if 'main' in self.dirty_tabs:
            safe_text = json.dumps(self.answer_buffer)
            self.answer_view.page().runJavaScript(f"typeof window.updateText === 'function' ? window.updateText({safe_text}) : null;")
            self.dirty_tabs.remove('main')
        
        for name, tab in self.verify_tabs.items():
            if name in self.dirty_tabs:
                safe_text = json.dumps(tab.buffer)
                tab.view.page().runJavaScript(f"typeof window.updateText === 'function' ? window.updateText({safe_text}) : null;")
                self.dirty_tabs.remove(name)
                
        if 'ocr' in self.dirty_tabs:
            safe_text = json.dumps(self.ocr_tab.buffer)
            self.ocr_tab.view.page().runJavaScript(f"typeof window.updateText === 'function' ? window.updateText({safe_text}) : null;")
            self.dirty_tabs.remove('ocr')
                
        if 'aggregator' in self.dirty_tabs:
            safe_text = json.dumps(self.aggregator_tab.buffer)
            self.aggregator_tab.view.page().runJavaScript(f"typeof window.updateText === 'function' ? window.updateText({safe_text}) : null;")
            self.dirty_tabs.remove('aggregator')

    def _start_worker(self, worker):
        self.active_workers.append(worker)
        worker.finished.connect(lambda: self.active_workers.remove(worker))
        worker.start()

    def on_send(self):
        question = self.input_edit.toPlainText().strip()
        if not question and not self.images_b64: return
        
        self.send_btn.setEnabled(False)
        self.input_edit.clear()
        self.history_label.setText(f"当前提问：{question if question else '[纯图片提问]'}")
        
        self.finished_reports = {}
        self.answer_buffer = ""
        self.raw_main_buffer = ""
        self.is_main_ocr_done = False
        self.dirty_tabs.clear()
        self.stage = "main"
        self.extracted_text = ""
        
        ThinkingController.start(self.answer_view)
        for name, tab in self.verify_tabs.items():
            tab.buffer = ""
            ThinkingController.waiting(tab.view)
            if tab.enable_btn: tab.enable_btn.show()
            
        self.ocr_tab.buffer = ""
        self.aggregator_tab.buffer = ""
        ThinkingController.waiting(self.aggregator_tab.view)
        
        if self.images_b64:
            if self.tab_widget.indexOf(self.ocr_tab) == -1:
                self.tab_widget.insertTab(0, self.ocr_tab, " 图片提取原文")
            ThinkingController.start(self.ocr_tab.view)
        else:
            if self.tab_widget.indexOf(self.ocr_tab) != -1:
                self.tab_widget.removeTab(self.tab_widget.indexOf(self.ocr_tab))
        
        self.status.setText("主模型分析中...")

        system_prompt = f"""今天是 {TODAY_STR}。请使用标准的 Markdown 语法。
【 解题核心指令 】：
1. 如果是**数学、物理、化学、编程等理科题目**，**必须给出完整的、一步一步的推导和计算过程**，严禁直接跳答案。
2. 如果是**英语阅读理解、语文、历史等文科题目**，直接给出最终答案，并附带必要的解析和原文定位即可。
"""
        if self.images_b64:
            system_prompt += f"""
【 图片识别特殊指令】：用户上传了 {len(self.images_b64)} 张图片。请你在回答的最开头，先使用 `【图片原文提取】` 作为标题。
**你必须按顺序（图1、图2...）确保提取了每一张图片里的所有文字，绝对不能遗漏任何一张图的内容。请用 `【图1原文】` 和 `【图2原文】` 等标记隔开。**
在所有文字提取完毕后，**必须使用 `---` 分割线隔开**，然后再给出你的推导和解答。
"""
        
        current_user_msg = {"role": "user", "content": ImageHandler.build_multimodal_content(question, self.images_b64)}
        messages = [{"role": "system", "content": system_prompt}] + self.chat_history + [current_user_msg]
        self.chat_history.append({"role": "user", "content": question if question else "[图]"})
        
        worker = StreamWorker(MAIN_BASE_URL, MAIN_API_KEY, MAIN_MODEL, messages, use_proxy=False)
        worker.chunk.connect(self._on_main_chunk)
        worker.done.connect(lambda full: self._on_main_done(question, full))
        worker.error.connect(lambda err: self._on_specific_error(err, "主回答"))
        self._start_worker(worker)

    def _on_main_chunk(self, text):
        self.raw_main_buffer += text
        
        if self.images_b64:
            if "---" in self.raw_main_buffer:
                if not self.is_main_ocr_done:
                    self.is_main_ocr_done = True
                    parts = self.raw_main_buffer.split("---", 1)
                    self.ocr_tab.buffer = parts[0].strip()
                    self.answer_buffer = parts[1].lstrip()
                else:
                    parts = self.raw_main_buffer.split("---", 1)
                    self.answer_buffer = parts[1].lstrip()
                    
                self.dirty_tabs.add('ocr')
                self.dirty_tabs.add('main')
            else:
                self.ocr_tab.buffer = self.raw_main_buffer
                self.dirty_tabs.add('ocr')
        else:
            self.answer_buffer = self.raw_main_buffer
            self.dirty_tabs.add('main')

    def _on_main_done(self, question, answer):
        self.dirty_tabs.discard('main')
        self.dirty_tabs.discard('ocr')

        if self.images_b64 and not self.is_main_ocr_done:
            self.answer_buffer = self.raw_main_buffer
            self.ocr_tab.buffer = "⚠️ 模型未按格式提取原文。"
        elif self.images_b64:
            parts = self.raw_main_buffer.split("---", 1)
            self.extracted_text = parts[0].strip() if len(parts) > 0 else ""
        else:
            self.answer_buffer = answer

        self.main_answer = self.answer_buffer
        self.chat_history.append({"role": "assistant", "content": self.answer_buffer})
        
        safe_text = json.dumps(self.answer_buffer)
        self.answer_view.page().runJavaScript(f"typeof window.forceRender === 'function' ? window.forceRender({safe_text}) : null;")
        
        if self.images_b64:
            safe_ocr = json.dumps(self.ocr_tab.buffer)
            self.ocr_tab.view.page().runJavaScript(f"typeof window.forceRender === 'function' ? window.forceRender({safe_ocr}) : null;")
        
        for name in CLOUD_VERIFIERS:
            ThinkingController.start(self.verify_tabs[name].view)
        
        self.stage = "cloud"
        self.status.setText("云端模型审查中...")
        
        delay = 0
        for name, cfg in CLOUD_VERIFIERS.items():
            is_vision_model = "Gemini" in name
            
            if self.images_b64 and is_vision_model:
                v_content = [
                    {"type": "text", "text": build_verification_prompt(question, self.main_answer, False, True) + "\n【注意】：用户上传了原图，请结合原图审查。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{self.images_b64[0]}"}}
                ]
                v_messages = [{"role": "user", "content": v_content}]
            elif self.images_b64 and not is_vision_model:
                text_prompt = f"用户上传了图片，前置模型为你提取了原文内容：\n\n{self.extracted_text}\n\n基于上述原文，请审查以下回答：\n{self.main_answer}"
                v_messages = [{"role": "user", "content": text_prompt}]
            else:
                v_prompt = build_verification_prompt(question, self.main_answer, False, False)
                v_messages = [{"role": "user", "content": v_prompt}]
            
            worker = StreamWorker(cfg["url"], cfg["key"], cfg["model"], v_messages, use_proxy=True)
            worker.chunk.connect(lambda t, n=name: self._on_verify_chunk(n, t))
            worker.done.connect(lambda full, n=name: self._on_verify_done(n, full, "cloud"))
            worker.error.connect(lambda err, n=name: self._on_specific_error(err, n))
            
            QTimer.singleShot(delay, lambda w=worker: self._start_worker(w))
            delay += 3000

    def _on_verify_chunk(self, name, text):
        if name not in self.verify_tabs: return
        tab = self.verify_tabs[name]
        tab.buffer += text
        self.dirty_tabs.add(name)

    def _on_verify_done(self, name, full_report, stage):
        if name not in self.verify_tabs: return
        tab = self.verify_tabs[name]
        
        self.dirty_tabs.discard(name)
        safe_text = json.dumps(tab.buffer)
        tab.view.page().runJavaScript(f"typeof window.forceRender === 'function' ? window.forceRender({safe_text}) : null;")
        self.finished_reports[name] = full_report
        
        if stage == "cloud":
            cloud_done = all(n in self.finished_reports for n in CLOUD_VERIFIERS)
            if cloud_done and self.stage == "cloud":
                self.stage = "local_waiting"
                self.status.setText("云端审查完毕。如需本地模型审查，请点击【本地标签页下的 ▶ 启用】；否则直接点【详细版/简略版】。")

    def _start_local_verifiers(self):
        if self.stage != "local_waiting": return
        self.stage = "local"
        self.status.setText("本地模型审查中...")
        
        for name in LOCAL_VERIFIERS:
            if self.verify_tabs[name].enable_btn:
                self.verify_tabs[name].enable_btn.hide()
            ThinkingController.start(self.verify_tabs[name].view)
        
        question = self.chat_history[-2]["content"] if len(self.chat_history) >=2 else ""
        delay = 0
        for name, cfg in LOCAL_VERIFIERS.items():
            if self.images_b64 and self.extracted_text:
                text_prompt = f"用户上传了图片，前置模型提取了原文内容：\n\n{self.extracted_text}\n\n请审查以下回答：\n{self.main_answer}"
                v_messages = [{"role": "user", "content": text_prompt}]
            else:
                v_prompt = build_verification_prompt(question, self.main_answer, True, False) 
                v_messages = [{"role": "user", "content": v_prompt}]

            worker = StreamWorker(cfg["url"], cfg["key"], cfg["model"], v_messages, use_proxy=False)
            worker.chunk.connect(lambda t, n=name: self._on_verify_chunk(n, t))
            worker.done.connect(lambda full, n=name: self._on_verify_done(n, full, "local"))
            worker.error.connect(lambda err, n=name: self._on_specific_error(err, n))
            
            QTimer.singleShot(delay, lambda w=worker: self._start_worker(w))
            delay += 3000

    def _skip_local_models(self):
        for name in LOCAL_VERIFIERS:
            if name not in self.finished_reports:
                self.finished_reports[name] = "[用户未启用本地模型验证]"
                tab = self.verify_tabs[name]
                tab.buffer = "⏭️ 用户未启用本地模型验证。"
                safe_text = json.dumps(tab.buffer)
                tab.view.page().runJavaScript(f"typeof window.forceRender === 'function' ? window.forceRender({safe_text}) : null;")
                if tab.enable_btn: tab.enable_btn.hide()
        self.stage = "agg"

    def _on_specific_error(self, err_msg, model_name):
        short_err = "未知错误"
        if "429" in err_msg or "quota" in err_msg.lower() or "exhausted" in err_msg.lower():
            short_err = "额度耗尽或触发限流 (429)"
        elif "Connection" in err_msg or "connect" in err_msg.lower():
            short_err = "网络连接失败，请检查网络或代理"
        elif "Timeout" in err_msg:
            short_err = "请求超时"
        else:
            last_line = err_msg.strip().splitlines()[-1] if err_msg.strip() else "未知错误"
            short_err = last_line[:80] + "..." if len(last_line) > 80 else last_line
        
        if model_name == "主回答":
            self.answer_view.page().runJavaScript(f"typeof window.forceRender === 'function' ? window.forceRender({json.dumps('<h3 style=color:red>失败: '+short_err+'</h3>')}) : null;")
            self.status.setText("❌ 失败")
            self.send_btn.setEnabled(True)
            QMessageBox.critical(self, "主模型错误", short_err)
        elif model_name == "综合结论":
            self.aggregator_tab.view.page().runJavaScript(f"typeof window.forceRender === 'function' ? window.forceRender({json.dumps('<h3 style=color:red>失败: '+short_err+'</h3>')}) : null;")
            self.send_btn.setEnabled(True)
        else:
            tab = self.verify_tabs[model_name]
            self.dirty_tabs.discard(model_name)
            tab.buffer = f"❌ 验证失败: {short_err}"
            safe_text = json.dumps(tab.buffer)
            tab.view.page().runJavaScript(f"typeof window.forceRender === 'function' ? window.forceRender({safe_text}) : null;")
            
            self.finished_reports[model_name] = "[该模型因网络、额度或限流原因未能提供有效意见]"
            
            if model_name in CLOUD_VERIFIERS:
                cloud_done = all(n in self.finished_reports for n in CLOUD_VERIFIERS)
                if cloud_done and self.stage == "cloud":
                    self.stage = "local_waiting"
                    self.status.setText("云端审查完毕。如需本地模型审查，请点击【本地标签页下的 ▶ 启用】；否则直接点【详细版/简略版】。")
            elif model_name in LOCAL_VERIFIERS:
                local_done = all(n in self.finished_reports for n in LOCAL_VERIFIERS)
                if local_done and self.stage == "local":
                    self._request_aggregation(self.agg_mode)

    def _request_aggregation(self, mode="detail"):
        self.agg_mode = mode
        
        if mode == "detail":
            self.btn_detail.setStyleSheet("background-color: #005cc5; color: white; border: none; padding: 8px 16px; font-weight: bold;")
            self.btn_brief.setStyleSheet("background-color: #f6f8fa; color: #24292e; border: 1px solid #d1d5da; padding: 8px 16px;")
        else:
            self.btn_brief.setStyleSheet("background-color: #005cc5; color: white; border: none; padding: 8px 16px; font-weight: bold;")
            self.btn_detail.setStyleSheet("background-color: #f6f8fa; color: #24292e; border: 1px solid #d1d5da; padding: 8px 16px;")

        if self.stage == "local_waiting":
            self._skip_local_models()

        if self.stage != "agg":
            if len(self.finished_reports) == len(ALL_VERIFIERS):
                self.stage = "agg"
                self._do_aggregation_request()
            return

        if self.agg_worker and self.agg_worker.isRunning():
            self.agg_worker.terminate()
            self.agg_worker.wait()
            
            if self.aggregator_tab.buffer.strip():
                mode_name = "详细版" if mode == "detail" else "简略版"
                self.aggregator_tab.buffer += f"\n\n---\n\n**🔄 已手动切换为 {mode_name}，以下为新结果**\n\n"
            
            self.dirty_tabs.add('aggregator')
            safe_text = json.dumps(self.aggregator_tab.buffer)
            self.aggregator_tab.view.page().runJavaScript(f"typeof window.forceRender === 'function' ? window.forceRender({safe_text}) : null;")

        self._do_aggregation_request()

    def _do_aggregation_request(self):
        self.status.setText(f"综合结论生成中 ({'详细版' if self.agg_mode=='detail' else '简略版'})...")
        ThinkingController.start(self.aggregator_tab.view)
        
        # 标题和分割线
        title_text = "📋 详细版" if self.agg_mode == "detail" else "⚡ 简略版"
        header_html = f"""
        <div style="text-align: center; color: #0366d6; font-size: 18px; font-weight: bold; margin: 10px 0;">{title_text}</div>
        <hr style="border: 0; border-top: 1px solid #e0e0e0; margin-bottom: 20px;">
        """
        
        if not self.aggregator_tab.buffer:
            self.aggregator_tab.buffer = header_html
        else:
            self.aggregator_tab.buffer += header_html
            
        self.dirty_tabs.add('aggregator')
        self.aggregator_tab.view.page().runJavaScript(f"typeof window.updateText === 'function' ? window.updateText({json.dumps(self.aggregator_tab.buffer)}) : null;")
        
        self.answer_view.page().runJavaScript(f"typeof window.forceRender === 'function' ? window.forceRender({json.dumps(self.answer_buffer)}) : null;")
        for name, tab in self.verify_tabs.items():
            tab.view.page().runJavaScript(f"typeof window.forceRender === 'function' ? window.forceRender({json.dumps(tab.buffer)}) : null;")
        
        reports_text = "".join([f"\n### {n}\n{r}\n" for n, r in self.finished_reports.items()])
        
        template = DETAIL_PROMPT if self.agg_mode == "detail" else BRIEF_PROMPT
        prompt = template.format(question="见原始问题", answer=self.main_answer, reports=reports_text)
        
        self.agg_worker = StreamWorker(MAIN_BASE_URL, MAIN_API_KEY, MAIN_MODEL, [{"role": "user", "content": prompt}], use_proxy=False)
        self.agg_worker.chunk.connect(self._on_aggregator_chunk)
        self.agg_worker.done.connect(self._on_aggregator_done)
        self.agg_worker.error.connect(lambda err: self._on_specific_error(err, "综合结论"))
        self._start_worker(self.agg_worker)

    def _on_aggregator_chunk(self, text):
        self.aggregator_tab.buffer += text
        self.dirty_tabs.add('aggregator')

    def _on_aggregator_done(self, full_report):
        self.dirty_tabs.discard('aggregator')
        safe_text = json.dumps(self.aggregator_tab.buffer)
        self.aggregator_tab.view.page().runJavaScript(f"typeof window.forceRender === 'function' ? window.forceRender({safe_text}) : null;")
        self.status.setText(" 全部完成！")
        self.send_btn.setEnabled(True)
        self.stage = "idle"
        self.clear_image()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())