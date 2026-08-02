"""Eval harness: golden Q&A verification against corpus + ground truth."""

from datasheet_analyzer.evalh.citations import QuestionResult, verify_questions
from datasheet_analyzer.evalh.golden import load_golden

__all__ = ["QuestionResult", "load_golden", "verify_questions"]
