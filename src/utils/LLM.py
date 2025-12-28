import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Any

import json
import random  # 如果你需要随机打乱之类，可删
import requests
import aiohttp
from openai import OpenAI, AsyncOpenAI


HKUST_BASE_URL = "https://aigc-api.hkust-gz.edu.cn/v1/chat/completions"


class LLM:
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url

        # 如果是 HKUST 接口，用 requests/aiohttp 自己调，不初始化 SDK 客户端
        if base_url == HKUST_BASE_URL:
            self.sync_client: Optional[OpenAI] = None
            self.async_client: Optional[AsyncOpenAI] = None
        else:
            self.sync_client = OpenAI(api_key=api_key, base_url=base_url)
            self.async_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    # ========== 内部工具方法 ==========
    def _build_hkust_payload(self, prompt: str, model: str, temperature: float, max_tokens: int) -> Dict[str, Any]:
        return {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    # ========== 同步方法 ==========
    def generate(self, prompt: str, model: str, temperature: float = 0.5, max_tokens: int = 6000) -> str:
        """
        同步生成（单个请求）——针对 OpenAI 兼容 SDK 的接口。
        如果当前 base_url 是 HKUST，会报错，应该用 generate_by_hkust。
        """
        if self.sync_client is None:
            raise RuntimeError("当前 base_url 为 HKUST，请使用 generate_by_hkust()")

        response = self.sync_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    def generate_by_hkust(self, prompt: str, model: str, temperature: float = 0.5, max_tokens: int = 6000,) -> str:
        """
        HKUST API 同步生成
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        data = self._build_hkust_payload(prompt, model, temperature, max_tokens)

        try:
            response = requests.post(
                url=self.base_url,
                headers=headers,
                data=json.dumps(data),
                timeout=60,
            )
            # print(response)
            response.raise_for_status()  # 检查 HTTP 错误
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except requests.exceptions.RequestException as e:
            raise Exception(f"HKUST API 请求失败: {str(e)}")
        except (KeyError, IndexError) as e:
            raise Exception(f"HKUST API 响应格式错误: {str(e)}")

    def batch_generate(self, prompts: List[str], model: str, temperature: float = 0.5, max_tokens: int = 6000, max_workers: int = 5, use_hkust: bool = False, retry_failed: bool = True, max_retries: int = 2,) -> List[Dict]:
        """
        同步批量生成，使用线程池并行加速。

        :param prompts: 文本列表
        :param model: 模型名
        :param max_workers: 线程池最大并发数
        :param use_hkust: True 时调用 HKUST 接口，否则调用 SDK generate()
        """
        def worker(idx: int, prompt: str) -> Dict:
            retry_count = 0
            while True:
                try:
                    if use_hkust:
                        content = self.generate_by_hkust(prompt, model, temperature, max_tokens)
                    else:
                        content = self.generate(prompt, model, temperature, max_tokens)
                    return {
                        "index": idx,
                        "prompt": prompt,
                        "response": content,
                        "success": True,
                        "error": None,
                        "retry_count": retry_count,
                    }
                except Exception as e:
                    if retry_failed and retry_count < max_retries:
                        retry_count += 1
                        continue
                    return {
                        "index": idx,
                        "prompt": prompt,
                        "response": None,
                        "success": False,
                        "error": str(e),
                        "retry_count": retry_count,
                    }

        results: List[Dict] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(worker, i, p): i for i, p in enumerate(prompts)
            }
            for future in as_completed(future_to_idx):
                res = future.result()
                results.append(res)

        # 按 index 排序，保证结果顺序和 prompts 一致
        results.sort(key=lambda x: x["index"])
        return results

    # ========== 异步方法 ==========
    async def async_generate(self, prompt: str, model: str, temperature: float = 0.5, max_tokens: int = 6000,) -> str:
        """
        异步生成（单个请求）——针对 OpenAI 兼容 SDK 的接口。
        """
        if self.async_client is None:
            raise RuntimeError("当前 base_url 为 HKUST，请使用 async_generate_by_hkust()")

        response = await self.async_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    async def async_generate_by_hkust(self, prompt: str, model: str, temperature: float = 0.5, max_tokens: int = 6000,) -> str:
        """
        HKUST API 异步生成
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        data = self._build_hkust_payload(prompt, model, temperature, max_tokens)

        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.post(
                    url=self.base_url,
                    headers=headers,
                    data=json.dumps(data),
                ) as resp:
                    resp.raise_for_status()
                    result = await resp.json()
                    return result["choices"][0]["message"]["content"]
            except aiohttp.ClientError as e:
                raise Exception(f"HKUST API 异步请求失败: {str(e)}")
            except (KeyError, IndexError) as e:
                raise Exception(f"HKUST API 响应格式错误: {str(e)}")

    async def async_batch_generate(self, prompts: List[str], model: str, temperature: float = 0.5, max_tokens: int = 6000, batch_size: int = 5, retry_failed: bool = True, max_retries: int = 2,) -> List[Dict]:
        """
        异步批量生成，使用 SDK 接口。
        """
        async def process_single(idx: int, prompt: str, retry_count: int = 0) -> Dict:
            try:
                content = await self.async_generate(prompt, model, temperature, max_tokens)
                return {
                    "index": idx,
                    "prompt": prompt,
                    "response": content,
                    "success": True,
                    "error": None,
                    "retry_count": retry_count,
                }
            except Exception as e:
                if retry_failed and retry_count < max_retries:
                    await asyncio.sleep(1 * (retry_count + 1))
                    return await process_single(idx, prompt, retry_count + 1)

                return {
                    "index": idx,
                    "prompt": prompt,
                    "response": None,
                    "success": False,
                    "error": str(e),
                    "retry_count": retry_count,
                }

        results: List[Dict] = []
        total_batches = (len(prompts) + batch_size - 1) // batch_size

        for batch_idx in range(0, len(prompts), batch_size):
            batch = prompts[batch_idx : batch_idx + batch_size]
            tasks = [
                process_single(batch_idx + j, p)
                for j, p in enumerate(batch)
            ]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)

            current_batch = batch_idx // batch_size + 1
            print(f"已完成批次 {current_batch}/{total_batches}")

        return results

    async def async_batch_generate_by_hkust(self, prompts: List[str], model: str, temperature: float = 0.9, max_tokens: int = 3000, batch_size: int = 5,) -> List[Dict]:
        """
        HKUST API 异步批量生成
        """
        results: List[Dict] = []

        async def process_single(idx: int, prompt: str) -> Dict:
            try:
                content = await self.async_generate_by_hkust(prompt, model, temperature, max_tokens)
                return {
                    "index": idx,
                    "prompt": prompt,
                    "response": content,
                    "success": True,
                    "error": None,
                }
            except Exception as e:
                return {
                    "index": idx,
                    "prompt": prompt,
                    "response": None,
                    "success": False,
                    "error": str(e),
                }

        total_batches = (len(prompts) + batch_size - 1) // batch_size

        for i in range(0, len(prompts), batch_size):
            batch = prompts[i : i + batch_size]
            tasks = [process_single(i + j, p) for j, p in enumerate(batch)]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
            print(f"已完成批次 {(i // batch_size) + 1}/{total_batches}")

        return results


# ---------- 使用示例 ----------
def test_sync_hkust():
    print("=" * 20, "同步 HKUST 测试", "=" * 20)
    gpt = LLM(api_key="", base_url=HKUST_BASE_URL,)

    # 1. 单个请求
    print("\n[同步-HKUST] 单个请求：")
    resp = gpt.generate_by_hkust("用一句话介绍你自己。", model="gpt-4")
    print("响应：", resp)

    # 2. 批量请求
    print("\n[同步-HKUST] 批量请求：")
    prompts = ["问题1：用一句话介绍广州", "问题2：Python 的优点是什么", "问题3：什么是异步编程"]
    results = gpt.batch_generate(
        prompts,
        model="gpt-4",
        max_workers=3,
        use_hkust=True,  # 必须 True，表示走 HKUST 的 generate_by_hkust
    )
    for r in results:
        print(f"index={r['index']} success={r['success']} retry={r['retry_count']}")
        print("  prompt :", r["prompt"])
        print("  resp   :", r["response"])
        print("-" * 40)

async def test_async_hkust():
    print("=" * 20, "异步 HKUST 测试", "=" * 20)
    gpt = LLM(
        api_key="",
        base_url=HKUST_BASE_URL,
    )

    # 1. 单个请求
    print("\n[异步-HKUST] 单个请求：")
    resp = await gpt.async_generate_by_hkust("用一句话解释什么是大语言模型。", model="gpt-4")
    print("响应：", resp)

    # 2. 批量请求
    print("\n[异步-HKUST] 批量请求：")
    prompts = [f"问题{i}：给我一个冷知识" for i in range(1, 11)]
    results = await gpt.async_batch_generate_by_hkust(
        prompts, model="gpt-4", batch_size=4
    )
    for r in results:
        print(f"index={r['index']} success={r['success']}")
        print("  prompt :", r["prompt"])
        print("  resp   :", r["response"])
        print("-" * 40)

def test_sync_sdk():
    print("=" * 20, "同步 SDK 接口测试", "=" * 20)
    gpt = LLM(
        api_key="你的OPENAI_COMPAT_API_KEY",
        base_url="https://api.openai.com/v1",  # 举例：官方/其他兼容服务
    )

    # 1. 单个请求
    print("\n[同步-SDK] 单个请求：")
    resp = gpt.generate("简要说明一下什么是协程。", model="gpt-4o")
    print("响应：", resp)

    # 2. 批量请求（使用 SDK）
    print("\n[同步-SDK] 批量请求：")
    prompts = ["解释 CPU 和 GPU 的区别", "解释什么是线程池", "解释 HTTP 和 HTTPS 的区别"]
    results = gpt.batch_generate(
        prompts,
        model="gpt-4o",
        max_workers=3,
        use_hkust=False,  # 走 generate()
    )
    for r in results:
        print(f"index={r['index']} success={r['success']} retry={r['retry_count']}")
        print("  prompt :", r["prompt"])
        print("  resp   :", r["response"])
        print("-" * 40)

async def test_async_sdk():
    print("=" * 20, "异步 SDK 接口测试", "=" * 20)
    gpt = LLM(
        api_key="你的OPENAI_COMPAT_API_KEY",
        base_url="https://api.openai.com/v1",  # 举例
    )

    # 1. 单个请求
    print("\n[异步-SDK] 单个请求：")
    resp = await gpt.async_generate("什么是事件循环？", model="gpt-4o")
    print("响应：", resp)

    # 2. 批量请求
    print("\n[异步-SDK] 批量请求：")
    prompts = [f"给我一个 Python 小技巧 {i}" for i in range(1, 8)]
    results = await gpt.async_batch_generate(
        prompts,
        model="gpt-4o",
        batch_size=3,
        retry_failed=True,
        max_retries=2,
    )
    for r in results:
        print(f"index={r['index']} success={r['success']} retry={r['retry_count']}")
        print("  prompt :", r["prompt"])
        print("  resp   :", r["response"])
        print("-" * 40)

if __name__ == "__main__":
    # 1. 测试 HKUST 同步
    test_sync_hkust()

    # 2. 测试 HKUST 异步
    # asyncio.run(test_async_hkust())

    # 3. 测试 SDK 同步
    # test_sync_sdk()

    # 4. 测试 SDK 异步
    # asyncio.run(test_async_sdk())

    pass
