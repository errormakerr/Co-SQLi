"""
LLM client wrapper supporting both OpenAI-compatible SDKs and the HKUST API.

Provides synchronous and asynchronous generation methods, including batched
parallel requests via thread pools (sync) or asyncio (async).
"""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import aiohttp
import requests
from openai import AsyncOpenAI, OpenAI


# Base URL for the HKUST internal API gateway
HKUST_BASE_URL = "https://aigc-api.hkust-gz.edu.cn/v1/chat/completions"


class LLM:
    """
    Unified LLM client.

    Supports two backends:
    - **OpenAI-compatible SDK** (default): any endpoint that follows the OpenAI
      ``/chat/completions`` schema (including local vLLM servers).
    - **HKUST gateway** (``base_url == HKUST_BASE_URL``): uses a raw HTTP POST
      rather than the SDK because the gateway does not expose an OpenAI-SDK
      compatible interface.
    """

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self._is_hkust = (base_url == HKUST_BASE_URL)

        if self._is_hkust:
            # Raw HTTP mode — SDK clients are not created
            self.sync_client: Optional[OpenAI] = None
            self.async_client: Optional[AsyncOpenAI] = None
        else:
            self.sync_client = OpenAI(api_key=api_key, base_url=base_url)
            self.async_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_hkust_payload(
        self,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> Dict[str, Any]:
        """Build the request body for the HKUST API."""
        return {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    # ------------------------------------------------------------------
    # Synchronous methods
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.5,
        max_tokens: int = 6000,
    ) -> str:
        """
        Synchronous single-request generation via the OpenAI-compatible SDK.

        Raises:
            RuntimeError: When the current ``base_url`` is the HKUST gateway.
                          Use :meth:`generate_by_hkust` instead.
        """
        if self.sync_client is None:
            raise RuntimeError(
                "Current base_url is the HKUST gateway — use generate_by_hkust() instead."
            )
        response = self.sync_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    def generate_by_hkust(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.5,
        max_tokens: int = 6000,
    ) -> str:
        """Synchronous single-request generation via the HKUST API gateway."""
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
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except requests.exceptions.RequestException as e:
            raise Exception(f"HKUST API request failed: {e}") from e
        except (KeyError, IndexError) as e:
            raise Exception(f"Unexpected HKUST API response format: {e}") from e

    def chat(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.5,
        max_tokens: int = 6000,
    ) -> str:
        """
        Unified synchronous generation — automatically routes to the correct
        backend (OpenAI SDK or HKUST gateway) based on ``base_url``.
        """
        if self._is_hkust:
            return self.generate_by_hkust(prompt, model, temperature, max_tokens)
        return self.generate(prompt, model, temperature, max_tokens)

    def batch_generate(
        self,
        prompts: List[str],
        model: str,
        temperature: float = 0.5,
        max_tokens: int = 6000,
        max_workers: int = 5,
        use_hkust: bool = False,
        retry_failed: bool = True,
        max_retries: int = 2,
    ) -> List[Dict]:
        """
        Synchronous batched generation using a thread pool.

        Args:
            prompts: List of prompt strings.
            model: Model name to use.
            max_workers: Maximum thread-pool concurrency.
            use_hkust: If ``True``, calls :meth:`generate_by_hkust`; otherwise
                       calls :meth:`generate`.
            retry_failed: Retry failed requests up to *max_retries* times.
            max_retries: Maximum number of retries per request.

        Returns:
            List of result dicts (same order as *prompts*), each containing:
            ``index``, ``prompt``, ``response``, ``success``, ``error``,
            ``retry_count``.
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
                results.append(future.result())

        results.sort(key=lambda x: x["index"])
        return results

    # ------------------------------------------------------------------
    # Asynchronous methods
    # ------------------------------------------------------------------

    async def async_generate(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.5,
        max_tokens: int = 6000,
    ) -> str:
        """
        Asynchronous single-request generation via the OpenAI-compatible SDK.

        Raises:
            RuntimeError: When the current ``base_url`` is the HKUST gateway.
                          Use :meth:`async_generate_by_hkust` instead.
        """
        if self.async_client is None:
            raise RuntimeError(
                "Current base_url is the HKUST gateway — use async_generate_by_hkust() instead."
            )
        response = await self.async_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    async def async_generate_by_hkust(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.5,
        max_tokens: int = 6000,
    ) -> str:
        """Asynchronous single-request generation via the HKUST API gateway."""
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
                raise Exception(f"HKUST async request failed: {e}") from e
            except (KeyError, IndexError) as e:
                raise Exception(f"Unexpected HKUST API response format: {e}") from e

    async def async_batch_generate(
        self,
        prompts: List[str],
        model: str,
        temperature: float = 0.5,
        max_tokens: int = 6000,
        batch_size: int = 5,
        retry_failed: bool = True,
        max_retries: int = 2,
    ) -> List[Dict]:
        """
        Asynchronous batched generation using asyncio concurrency.

        Requests are processed in mini-batches of *batch_size* to avoid
        overwhelming the server.

        Args:
            prompts:      List of prompt strings.
            model:        Model name to use.
            batch_size:   Concurrency per mini-batch.
            retry_failed: Retry failed requests up to *max_retries* times.
            max_retries:  Maximum number of retries per request.

        Returns:
            List of result dicts in the same order as *prompts*.
        """

        async def process_single(idx: int, prompt: str, retry_count: int = 0) -> Dict:
            try:
                content = await self.async_generate(
                    prompt, model, temperature, max_tokens
                )
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
            batch = prompts[batch_idx: batch_idx + batch_size]
            tasks = [process_single(batch_idx + j, p) for j, p in enumerate(batch)]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
            current_batch = batch_idx // batch_size + 1
            print(f"Completed batch {current_batch}/{total_batches}")

        return results

    async def async_batch_generate_by_hkust(
        self,
        prompts: List[str],
        model: str,
        temperature: float = 0.9,
        max_tokens: int = 3000,
        batch_size: int = 5,
    ) -> List[Dict]:
        """
        Asynchronous batched generation via the HKUST API gateway.

        Returns:
            List of result dicts in the same order as *prompts*.
        """

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

        results: List[Dict] = []
        total_batches = (len(prompts) + batch_size - 1) // batch_size

        for i in range(0, len(prompts), batch_size):
            batch = prompts[i: i + batch_size]
            tasks = [process_single(i + j, p) for j, p in enumerate(batch)]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
            print(f"Completed batch {(i // batch_size) + 1}/{total_batches}")

        return results
