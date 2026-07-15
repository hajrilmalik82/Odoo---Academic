import threading
import requests
import logging
import html
import re
from odoo import api, models

_logger = logging.getLogger(__name__)

def clean_html(raw_html):
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return html.unescape(cleantext).strip()

def send_to_n8n_async(webhook_url, payload, token):
    try:
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        requests.post(webhook_url, json=payload, headers=headers, timeout=10)
    except Exception as e:
        _logger.error(f"Failed to send message to n8n: {e}")

class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        
        try:
            if self.channel_type == 'livechat':
                author = message.author_id
                # Check if the author is an internal user (staff/admin) to prevent infinite loops
                is_internal = False
                if message.author_id:
                    # OdooBot is not always in group_user, so check its specific ID
                    if message.author_id.id == self.env.ref('base.partner_root').id:
                        is_internal = True
                    elif message.author_id.user_ids:
                        is_internal = any(u.has_group('base.group_user') for u in message.author_id.user_ids)
                
                # Only process messages from external users (guests/visitors)
                if not is_internal and message.message_type == 'comment':
                    webhook_url = self.env['ir.config_parameter'].sudo().get_param('campus_portal.n8n_webhook_url')
                    webhook_token = self.env['ir.config_parameter'].sudo().get_param('campus_portal.n8n_webhook_token')
                    
                    if webhook_url:
                        # Extract plain text from HTML message body
                        clean_body = clean_html(message.body)
                        
                        if clean_body:
                            payload = {
                                'channel_id': self.id,
                                'message_id': message.id,
                                'author_name': author.name if author else 'Public User',
                                'message': clean_body
                            }
                            
                            # Send asynchronously to avoid blocking the chat UI
                            thread = threading.Thread(target=send_to_n8n_async, args=(webhook_url, payload, webhook_token))
                            thread.start()
        except Exception as e:
            _logger.error(f"Error in Live Chat AI Integration: {e}")
            
        return message
