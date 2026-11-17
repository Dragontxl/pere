"""Agnes AI 客户端适配器

Agnes 3.0 Flash 是 OpenAI 兼容的文本模型 API，
本适配器将 requests 调用封装为与 OpenAI/ZhipuAI SDK 相同的接口，
使现有代码无需修改调用方式即可切换到 Agnes。

API 文档：https://agnes-ai.com/zh-Hans/docs/agnes-30-flash
"""

import requests


class _Choice:
    """模拟 OpenAI Choice 对象"""

    def __init__(self, message):
        self.message = message


class _Message:
    """模拟 OpenAI Message 对象"""

    def __init__(self, content):
        self.role = "assistant"
        self.content = content


class _Completion:
    """模拟 OpenAI ChatCompletion 对象"""

    def __init__(self, content):
        self.choices = [_Choice(_Message(content))]


class _ChatCompletions:
    """模拟 client.chat.completions 接口"""

    def __init__(self, base_url: str, api_key: str, timeout: int = 180, max_retries: int = 3):
        self._base_url = base_url
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries

    def create(self, model: str, messages: list, **kwargs) -> _Completion:
        """创建对话补全

        超时或网络错误时自动重试，最多 max_retries 次，指数退避。

        Args:
            model: 模型名称
            messages: 消息数组
            **kwargs: 其他参数（temperature, max_tokens 等）

        Returns:
            模拟的 ChatCompletion 对象
        """
        import time

        payload = {"model": model, "messages": messages}
        # 过滤掉 Agnes 不支持的参数
        for key in ("temperature", "top_p", "max_tokens", "stream"):
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]

        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = requests.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                return _Completion(data["choices"][0]["message"]["content"])
            except (requests.exceptions.ReadTimeout,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as e:
                last_error = e
                if attempt < self._max_retries:
                    wait = 5 * (2 ** attempt)  # 指数退避: 5s, 10s, 20s
                    print(f"  ⚠️ Agnes API 超时/网络错误（第 {attempt+1} 次），{wait}s 后重试...")
                    time.sleep(wait)
                    continue
                raise last_error
            except requests.exceptions.RequestException as e:
                # 非超时类错误，不重试
                raise


class _Chat:
    """模拟 client.chat 接口"""

    def __init__(self, base_url: str, api_key: str, timeout: int = 180, max_retries: int = 3):
        self.completions = _ChatCompletions(base_url, api_key, timeout, max_retries)


class AgnesClient:
    """Agnes AI 客户端

    接口与 OpenAI/ZhipuAI SDK 兼容，可直接用于现有代码。

    Example:
        client = AgnesClient(base_url="https://apihub.agnes-ai.com/v1", api_key="sk-xxx")
        response = client.chat.completions.create(
            model="agnes-3.0-flash",
            messages=[{"role": "user", "content": "你好"}],
        )
        print(response.choices[0].message.content)
    """

    def __init__(self, base_url: str = "https://apihub.agnes-ai.com/v1",
                 api_key: str = "", timeout: int = 180, max_retries: int = 3):
        self.chat = _Chat(base_url, api_key, timeout, max_retries)
