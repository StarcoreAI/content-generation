"""
豆包登录脚本 - 直接运行此文件
用法：python login.py
"""
import asyncio
import json
import os
from playwright.async_api import async_playwright

async def login():
    print("正在启动浏览器...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--start-maximized',
                '--disable-infobars',
            ]
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 800}
        )
        # 隐藏自动化特征
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = {runtime: {}};
        """)
        page = await context.new_page()
        print("正在打开豆包...")
        await page.goto('https://www.doubao.com/chat/')
        print("\n==========================================")
        print("请在弹出的浏览器窗口中登录豆包")
        print("登录成功后，回到这里按回车键保存")
        print("==========================================\n")
        input("登录完成后按回车键...")
        cookies = await context.cookies()
        os.makedirs('data', exist_ok=True)
        with open('data/doubao_cookies.json', 'w', encoding='utf-8') as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        print(f"\n✓ 登录成功！已保存 {len(cookies)} 个Cookie")
        await browser.close()
        print("浏览器已关闭，现在可以正常使用爬取功能了")

if __name__ == '__main__':
    asyncio.run(login())
