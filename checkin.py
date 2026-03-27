#!/usr/bin/env python3
"""
ModelScope 魔搭社区自动签到脚本
每日登录即可获得 150 魔粒
"""

import asyncio
import re
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from utils.notify import notify

load_dotenv()

MODELSCOPE_DOMAIN = 'https://modelscope.cn'


def mask_username(name: str) -> str:
	"""打码用户名，仅保留首尾字符，其余用*代替"""
	if not name:
		return '****'
	name = str(name)
	if len(name) <= 2:
		return name[0] + '***'
	return name[0] + '***' + name[-1]


def mask_email(email: str) -> str:
	"""打码邮箱，仅保留部分本地名和完整域名"""
	if not email or '@' not in email:
		return '****'
	email = str(email)
	local, domain = email.split('@', 1)
	if not local:
		return f'****@{domain}'
	if len(local) <= 2:
		masked_local = local[0] + '***'
	else:
		masked_local = local[0] + '***' + local[-1]
	return f'{masked_local}@{domain}'



def parse_cookies(cookies_str: str) -> list[dict]:
	"""将浏览器复制的 cookie 字符串解析为 Playwright cookie 列表"""
	cookies = []
	for item in cookies_str.split(';'):
		item = item.strip()
		if '=' in item:
			key, value = item.split('=', 1)
			cookies.append({
				'name': key.strip(),
				'value': value.strip(),
				'domain': '.modelscope.cn',
				'path': '/',
			})
	return cookies


async def check_in(account_name: str, cookies_str: str) -> tuple[bool, dict]:
	"""使用 Playwright 登录 ModelScope 完成签到

	Returns:
		(success, login_info)
	"""
	print(f'\n[PROCESSING] {account_name}: Starting browser...')

	playwright_cookies = parse_cookies(cookies_str)
	if not playwright_cookies:
		print(f'[FAILED] {account_name}: No valid cookies found')
		return False, {}

	print(f'[INFO] {account_name}: Parsed {len(playwright_cookies)} cookies')

	login_info = {}

	async with async_playwright() as p:
		browser = await p.chromium.launch(headless=True)
		context = await browser.new_context(
			user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
		)
		await context.add_cookies(playwright_cookies)
		page = await context.new_page()

		# 拦截用户信息 API 响应
		async def handle_response(response):
			if '/api/v1/users/login/info' in response.url and response.status == 200:
				try:
					data = await response.json()
					if data.get('Success') and data.get('Data'):
						login_info.update(data['Data'])
				except Exception:
					pass

		page.on('response', handle_response)

		try:
			overview_url = f'{MODELSCOPE_DOMAIN}/my/overview'
			print(f'[NETWORK] {account_name}: Navigating to {overview_url}')

			await page.goto(overview_url, wait_until='domcontentloaded', timeout=60000)
			await page.wait_for_timeout(5000)

			current_url = page.url
			title = await page.title()
			masked_url = re.sub(r'(modelscope\.cn/u/)([^/?#]+)', lambda m: m.group(1) + mask_username(m.group(2)), current_url)

			print(f'[INFO] {account_name}: Page title: {title}, URL: {masked_url}')

			# 检查是否被重定向到登录页
			if 'login' in current_url or 'passport' in current_url:
				print(f'[FAILED] {account_name}: Redirected to login page - cookies may be expired')
				await browser.close()
				return False, login_info

			# 验证登录状态
			if login_info.get('Name'):
				masked_name = mask_username(login_info["Name"])
				print(f'[SUCCESS] {account_name}: Login successful (user: {masked_name})')
				await browser.close()
				return True, login_info

			# 通过页面标题判断
			if '概览' in title or 'overview' in title.lower():
				print(f'[SUCCESS] {account_name}: Login successful (verified by page title)')
				await browser.close()
				return True, login_info

			print(f'[FAILED] {account_name}: Unable to verify login status')
			await browser.close()
			return False, login_info

		except Exception as e:
			print(f'[FAILED] {account_name}: Error during login - {str(e)[:80]}')
			await browser.close()
			return False, login_info


async def main():
	"""主函数"""
	print('[SYSTEM] ModelScope auto check-in script started')
	print(f'[TIME] {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

	# 从环境变量读取 cookies，支持多账号（用 ||| 分隔）
	cookies_str = os.getenv('MODELSCOPE_COOKIES', '')
	if not cookies_str:
		print('[FAILED] MODELSCOPE_COOKIES environment variable not set')
		sys.exit(1)

	# 支持多账号：用 ||| 分隔多个 cookie 字符串
	cookie_list = [c.strip() for c in cookies_str.split('|||') if c.strip()]
	print(f'[INFO] Found {len(cookie_list)} account(s)')

	success_count = 0
	total_count = len(cookie_list)
	notification_content = []

	for i, cookies in enumerate(cookie_list):
		account_name = f'Account {i + 1}'
		try:
			success, login_info = await check_in(account_name, cookies)

			if success:
				success_count += 1
				user_display = login_info.get('Name', 'Unknown')
				email = login_info.get('Email', 'N/A')
				masked_name = mask_username(user_display)
				masked_email = mask_email(email)
				result = f'[SUCCESS] {account_name}: {masked_name} ({masked_email})'
			else:
				result = f'[FAIL] {account_name}: Check-in failed'
				notification_content.append(result)

			print(result)

		except Exception as e:
			print(f'[FAILED] {account_name}: Exception - {e}')
			notification_content.append(f'[FAIL] {account_name}: {str(e)[:50]}')

	# 输出统计
	print(f'\n[STATS] Success: {success_count}/{total_count}')

	if success_count == total_count:
		print('[SUCCESS] All accounts check-in successful!')
	elif success_count > 0:
		print('[WARN] Some accounts check-in failed')
	else:
		print('[ERROR] All accounts check-in failed')

	# 失败时发送通知
	if notification_content:
		time_info = f'[TIME] {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
		notify_content = '\n'.join([time_info, *notification_content, f'Success: {success_count}/{total_count}'])
		notify.push_message('ModelScope Check-in Alert', notify_content, msg_type='text')
		print('[NOTIFY] Notification sent')

	sys.exit(0 if success_count > 0 else 1)


if __name__ == '__main__':
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		print('\n[WARNING] Interrupted')
		sys.exit(1)
	except Exception as e:
		print(f'\n[FAILED] {e}')
		sys.exit(1)
