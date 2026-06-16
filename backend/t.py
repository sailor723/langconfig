import asyncio, httpx, json

async def main():
    async with httpx.AsyncClient() as c:
        resp = await c.post('http://localhost:8765/api/custom-tools/generate-code',
            json={
                'prompt': 'A function that retrieves stored PDF text by session_id from a .chat_pdf_kv directory, with a max_chars parameter to limit text length',
                'function_name': 'get_pdf_context',
                'description': 'test'
            },
            timeout=60)
        data = resp.json()
        print(f'is_valid: {data.get("is_valid")}')
        code = data.get('code', '')
        print(f'code empty: {len(code) == 0}')
        if code:
            print(code[:300])
        if data.get('errors'):
            print(f'errors: {data["errors"]}')
        if data.get('parsed_schema'):
            print(f'schema: {json.dumps(data["parsed_schema"], indent=2)}')

asyncio.run(main())
