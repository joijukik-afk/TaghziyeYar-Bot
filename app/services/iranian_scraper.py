# app/services/iranian_scraper.py
import logging
from typing import Optional
from curl_cffi import requests as curl_requests
from pypasser.antibot import arvancloud
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class IranianScraper:
    def __init__(self):
        self.session = curl_requests.Session(impersonate="chrome120")
        self.session.headers.update({
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        })

    def _solve_arvancloud(self, url: str) -> bool:
        """حل چالش ArvanCloud و به‌روزرسانی کوکی‌های session."""
        try:
            logger.info(f"Attempting to solve ArvanCloud challenge for {url}")
            result = arvancloud.solve(url=url, timeout=30, attempts=3)
            if result.is_solved:
                for name, value in result.cookies.items():
                    self.session.cookies.set(name, value)
                self.session.headers["User-Agent"] = result.user_agent
                logger.info("ArvanCloud challenge solved successfully.")
                return True
            else:
                logger.warning("Failed to solve ArvanCloud challenge.")
        except Exception as e:
            logger.error(f"Error solving ArvanCloud: {e}")
        return False

    def fetch_page_content(self, url: str) -> Optional[str]:
        """دریافت محتوای یک صفحه با مدیریت هوشمند چالش‌ها."""
        try:
            # تلاش اول: درخواست با curl_cffi (جعل هویت مرورگر)
            response = self.session.get(url, timeout=30)
            if response.status_code == 200:
                return self._extract_text(response.text)
            
            # اگر با چالش ArvanCloud مواجه شدیم (کد 403 یا صفحه چالش)
            if response.status_code == 403 or "__arcsjs" in response.text:
                logger.info(f"ArvanCloud challenge detected for {url}. Solving...")
                if self._solve_arvancloud(url):
                    # تلاش دوم: درخواست مجدد با کوکی‌های حل‌شده
                    response = self.session.get(url, timeout=30)
                    if response.status_code == 200:
                        return self._extract_text(response.text)
            
            logger.warning(f"Failed to fetch {url}. Status: {response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
        return None

    def _extract_text(self, html: str) -> str:
        """استخراج متن تمیز از HTML."""
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe']):
            tag.decompose()
        texts = list(soup.stripped_strings)
        # فیلتر کردن متن‌های خیلی کوتاه
        filtered = [t for t in texts if len(t) > 5]
        return "\n".join(list(dict.fromkeys(filtered)))[:4000]

# یک نمونه سراسری برای استفاده مجدد
_scraper = IranianScraper()
def get_iranian_scraper() -> IranianScraper:
    return _scraper
