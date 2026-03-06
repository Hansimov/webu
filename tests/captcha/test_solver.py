from webu.captcha.solver import CaptchaSolver


def test_extract_response_text_from_list_payload():
    solver = CaptchaSolver(endpoint="https://example.com", verbose=False)
    data = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "reasoning", "text": "分析中"},
                        {"type": "text", "text": "[1, 3]"},
                    ]
                }
            }
        ]
    }

    assert solver._extract_response_text(data) == "分析中\n[1, 3]"
