from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CampusBuilding(models.Model):
    _name = 'campus.building'
    _description = 'Campus Building'
    _order = 'name'
    _check_company_auto = True

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code')
    location = fields.Char(string='Location', required=True, help="Example: Campus A Sudirman")
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)


class CampusRoom(models.Model):
    _name = 'campus.room'
    _description = 'Campus Room'
    _order = 'name'
    _check_company_auto = True

    name = fields.Char(string='Name', required=True)
    building_id = fields.Many2one('campus.building', string='Building', required=True, check_company=True)
    capacity = fields.Integer(string='Capacity', required=True)
    room_type = fields.Selection([
        ('theory', 'Theory'),
        ('lab', 'Laboratory')
    ], string='Room Type', required=True, default='theory')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.constrains('capacity')
    def _check_capacity(self):
        for record in self:
            if record.capacity <= 0:
                raise ValidationError(_("Room capacity must be greater than zero."))
