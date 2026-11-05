# thinking_ui.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import Signal

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/marked/9.1.6/marked.min.js"></script>
    <script>
    MathJax = {
      tex: {
        inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
        displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
        processEscapes: true
      },
      svg: { fontCache: 'global' },
      options: { enableMenu: false }
    };
    </script>
    <script id="MathJax-script" async src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.2/es5/tex-mml-chtml.min.js"></script>
    <style>
        body { font-family: 'Segoe UI', -apple-system, sans-serif; margin: 0; padding: 20px; font-size: 15px; line-height: 1.7; color: #24292e; height: 100vh; box-sizing: border-box; display: flex; flex-direction: column; background-color: #fafbfc; }
        #content { flex-grow: 1; overflow-y: auto; padding-right: 15px; white-space: pre-wrap; }
        
        h1, h2, h3 { border-bottom: 1px solid #eaecef; padding-bottom: 0.3em; margin-top: 1.5em; }
        blockquote { border-left: 4px solid #dfe2e5; color: #6a737d; padding-left: 1em; margin-left: 0; }
        pre { background: #f6f8fa; padding: 16px; border-radius: 6px; overflow: auto; font-size: 14px; }
        code { font-family: 'Consolas', monospace; background: rgba(27,31,35,.05); padding: 0.2em 0.4em; border-radius: 3px; }
        
        #thinking-box { display: none; align-items: center; gap: 12px; color: #0366d6; font-size: 15px; font-weight: bold; margin-top: 20px; }
        .spinner { width: 22px; height: 22px; border: 3px solid rgba(3, 102, 214, 0.2); border-top-color: #0366d6; border-radius: 50%; animation: spin 1s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <div id="thinking-box"><div class="spinner"></div><span>正在深度思考...</span></div>
    <div id="content"></div>
    <script>
        window.showThinking = function() { 
            let b = document.getElementById('thinking-box'); 
            let c = document.getElementById('content'); 
            if (b) b.style.display = "flex"; 
            if (c) { c.innerHTML = ""; c.style.whiteSpace = "pre-wrap"; } 
        }
        window.showWaiting = function() { 
            let b = document.getElementById('thinking-box'); 
            if (b) b.style.display = "none"; 
            let c = document.getElementById('content'); 
            if (c) { c.innerHTML = "<div style='color:#999; font-style:italic; padding-top:20px;'>等待前序任务完成...</div>"; c.style.whiteSpace = "normal"; } 
        }
        window.hideThinking = function() { 
            let b = document.getElementById('thinking-box'); 
            if (b) b.style.display = "none"; 
        }
        
        window.updateText = function(text) {
            if (typeof window.hideThinking === 'function') window.hideThinking();
            let c = document.getElementById('content');
            if (!c) return;
            c.style.whiteSpace = "pre-wrap";
            c.innerText = text;
            c.scrollTop = c.scrollHeight;
        }

        window.forceRender = function(text) {
            if (typeof window.hideThinking === 'function') window.hideThinking();
            
            let c = document.getElementById('content');
            if (!c) return;
            c.style.whiteSpace = "normal";
            
            let lines = text.split('\\n');
            let newLines = [];
            for(let i=0; i<lines.length; i++) {
                let line = lines[i].trim();
                if (line.length > 0 && !line.startsWith('$') && !line.startsWith('**') && !line.startsWith('-') && !line.startsWith('*') && /^\\\\[a-zA-Z]+/.test(line)) {
                    newLines.push('$$ ' + lines[i] + ' $$');
                } else {
                    newLines.push(lines[i]);
                }
            }
            let processedText = newLines.join('\\n');
            
            // 检查库是否加载完毕，没加载完就再试一次
            let attempts = 0;
            let timer = setInterval(() => {
                if (typeof marked !== 'undefined') {
                    clearInterval(timer);
                    try {
                        c.innerHTML = marked.parse(processedText);
                    } catch(e) {
                        c.innerText = text;
                    }
                    
                    function tryRender() {
                        if (window.MathJax && window.MathJax.typesetPromise) {
                            MathJax.typesetPromise([c]).catch(() => {});
                        }
                    }
                    tryRender(); 
                    setTimeout(tryRender, 500); 
                    setTimeout(tryRender, 1500);
                    setTimeout(tryRender, 3000);
                } else if (++attempts > 50) {
                    clearInterval(timer);
                    c.innerText = text;
                }
            }, 100);
            
            c.scrollTop = c.scrollHeight;
        }
    </script>
</body>
</html>
"""

class ThinkingController:
    @staticmethod
    def start(view):
        view.page().runJavaScript("typeof window.showThinking === 'function' ? window.showThinking() : null;")
    @staticmethod
    def waiting(view):
        view.page().runJavaScript("typeof window.showWaiting === 'function' ? window.showWaiting() : null;")
    @staticmethod
    def stop(view):
        view.page().runJavaScript("typeof window.hideThinking === 'function' ? window.hideThinking() : null;")

class VerificationTab(QWidget):
    enable_clicked = Signal()
    
    def __init__(self, model_name, is_local=False):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.model_label = QLabel(f"模型：{model_name}")
        self.model_label.setStyleSheet("color: #586069; font-size: 12px; padding: 6px 10px; background: #f1f8ff; border-bottom: 1px solid #e1e4e8;")
        layout.addWidget(self.model_label)
        
        self.enable_btn = None
        if is_local:
            self.enable_btn = QPushButton("▶ 启用本地模型验证")
            self.enable_btn.setStyleSheet("background-color: #ffa500; color: white; padding: 8px; font-weight: bold; margin: 10px; border-radius: 4px;")
            self.enable_btn.clicked.connect(self.enable_clicked.emit)
            layout.addWidget(self.enable_btn)
        
        self.view = QWebEngineView()
        self.view.setHtml(HTML_TEMPLATE)
        layout.addWidget(self.view)
        self.buffer = ""
        self.started = False

    def update_actual_model(self, name):
        self.model_label.setText(f"模型：{name} (实际执行)")