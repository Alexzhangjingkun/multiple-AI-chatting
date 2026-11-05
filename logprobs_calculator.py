# logprobs_calculator.py
import math

class LogprobsCalculator:
    def __init__(self):
        self.logprobs_list = []

    def add(self, logprobs_content):
        if logprobs_content:
            self.logprobs_list.extend([item.logprob for item in logprobs_content])

    def calculate_confidence(self) -> str:
        if not self.logprobs_list:
            return "未获取到"
        avg_logprob = sum(self.logprobs_list) / len(self.logprobs_list)
        return f"{math.exp(avg_logprob) * 100.0:.2f}%"