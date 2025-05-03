import logging
import asyncio
from playwright.async_api import Page
from typing import Optional, Dict, Any
import json
import aiohttp
import os
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class CloudflareBypassManager:
    def __init__(self):
        self.methods = [
            PlaywrightMethod(),
            FlareSolverrMethod(),
            DrissionMethod()
        ]
        self.current_method_index = 0
        self.success_count = 0
        self.fail_count = 0
        
    async def bypass(self, url: str) -> Optional[str]:
        """
        Try different methods to bypass Cloudflare protection
        Returns the page content if successful, None otherwise
        """
        for method in self.methods:
            try:
                logger.info(f"Attempting bypass with {method.__class__.__name__}")
                content = await method.bypass(url)
                if content and self._is_valid_content(content):
                    self.success_count += 1
                    logger.info(f"Successfully bypassed with {method.__class__.__name__}")
                    return content
            except Exception as e:
                logger.error(f"Bypass failed with {method.__class__.__name__}: {e}")
                self.fail_count += 1
                continue
        return None
    
    def _is_valid_content(self, content: str) -> bool:
        """Check if the content is valid (not a Cloudflare challenge page)"""
        if not content:
            return False
        
        # Check for common Cloudflare challenge indicators
        cf_indicators = [
            "Just a moment",
            "Checking your browser",
            "Please wait while we verify",
            "Please turn JavaScript on",
            "Enable JavaScript and cookies to continue"
        ]
        
        return not any(indicator in content for indicator in cf_indicators)

class PlaywrightMethod:
    def __init__(self):
        self.page: Optional[Page] = None
        self.context = None
        
    async def bypass(self, url: str) -> Optional[str]:
        """Use Playwright to bypass Cloudflare"""
        try:
            # Wait for Cloudflare challenge to complete
            await self.page.wait_for_load_state("networkidle", timeout=30000)
            
            # Additional wait for any remaining challenges
            await asyncio.sleep(5)
            
            # Check for and handle any remaining challenges
            if await self._handle_challenges():
                # Get the final page content
                content = await self.page.content()
                return content if content else None
                
        except Exception as e:
            logger.error(f"Playwright bypass failed: {e}")
            return None
            
    async def _handle_challenges(self) -> bool:
        """Handle any remaining Cloudflare challenges"""
        try:
            # Check for common challenge elements
            challenge_selectors = [
                "iframe[title*='challenge']",
                "#challenge-form",
                "#cf-challenge-running"
            ]
            
            for selector in challenge_selectors:
                try:
                    element = await self.page.wait_for_selector(selector, timeout=5000)
                    if element:
                        # Try to solve the challenge
                        await self._solve_challenge(selector)
                except:
                    continue
                    
            return True
            
        except Exception as e:
            logger.error(f"Error handling challenges: {e}")
            return False
            
    async def _solve_challenge(self, selector: str):
        """Attempt to solve a specific challenge"""
        # Add challenge-specific solutions here
        pass

class FlareSolverrMethod:
    def __init__(self):
        self.api_url = os.getenv("FLARESOLVERR_URL", "http://localhost:8191/v1")
        self.session_id = None
        
    async def bypass(self, url: str) -> Optional[str]:
        """Use FlareSolverr to bypass Cloudflare"""
        try:
            # Create or reuse session
            if not self.session_id:
                self.session_id = await self._create_session()
                
            # Prepare request data
            data = {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": 60000,
                "session": self.session_id,
                "cookies": []  # Add any required cookies here
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=data) as response:
                    result = await response.json()
                    
                    if result.get("status") == "ok":
                        return result.get("solution", {}).get("response")
                    else:
                        logger.error(f"FlareSolverr error: {result.get('message')}")
                        return None
                        
        except Exception as e:
            logger.error(f"FlareSolverr bypass failed: {e}")
            return None
            
    async def _create_session(self) -> str:
        """Create a new FlareSolverr session"""
        try:
            data = {
                "cmd": "sessions.create",
                "options": {}
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=data) as response:
                    result = await response.json()
                    return result.get("session")
        except Exception as e:
            logger.error(f"Failed to create FlareSolverr session: {e}")
            raise

class DrissionMethod:
    def __init__(self):
        self.page = None
        
    async def bypass(self, url: str) -> Optional[str]:
        """Use DrissionPage to bypass Cloudflare"""
        try:
            # Implementation using DrissionPage
            # This is a placeholder for the actual implementation
            return None
        except Exception as e:
            logger.error(f"DrissionPage bypass failed: {e}")
            return None 