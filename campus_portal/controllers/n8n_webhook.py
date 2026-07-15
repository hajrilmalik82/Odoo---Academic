import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class N8nWebhookController(http.Controller):
    
    @http.route('/api/v1/livechat/reply', type='json', auth='public', methods=['POST'], csrf=False)
    def livechat_ai_reply(self, **post):
        # 1. Verify token
        expected_token = request.env['ir.config_parameter'].sudo().get_param('campus_portal.n8n_webhook_token')
        
        # Check token in headers
        auth_header = request.httprequest.headers.get('Authorization')
        if expected_token and (not auth_header or auth_header != f'Bearer {expected_token}'):
            _logger.warning("Unauthorized AI reply attempt")
            return {'status': 'error', 'message': 'Unauthorized'}
            
        # 2. Extract payload
        data = post
        channel_id = data.get('channel_id')
        message = data.get('message')
        
        if not channel_id or not message:
            return {'status': 'error', 'message': 'Missing channel_id or message'}
            
        # 3. Post message to channel
        channel = request.env['discuss.channel'].sudo().browse(int(channel_id))
        if not channel.exists():
            return {'status': 'error', 'message': 'Channel not found'}
            
        # Find OdooBot to act as the AI author
        odoo_bot = request.env.ref('base.partner_root', raise_if_not_found=False)
        author_id = odoo_bot.id if odoo_bot else request.env.user.partner_id.id
            
        try:
            channel.message_post(
                body=message,
                author_id=author_id,
                message_type='comment',
                subtype_xmlid='mail.mt_comment'
            )
            return {'status': 'success', 'message': 'Reply posted'}
        except Exception as e:
            _logger.error(f"Failed to post AI reply: {e}")
            return {'status': 'error', 'message': str(e)}
