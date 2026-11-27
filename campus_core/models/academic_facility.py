from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CampusBuilding(models.Model):
    _name = 'campus.building'
    _description = 'Campus Building'
    _order = 'name'

    _check_code_unique = models.UniqueIndex(
        "(upper(code)) WHERE code IS NOT NULL AND code <> ''",
        "Building code must be unique!",
    )

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code')
    location = fields.Char(string='Location', required=True, help="Example: Campus A Sudirman")


class CampusRoom(models.Model):
    _name = 'campus.room'
    _description = 'Campus Room'
    _order = 'name'

    _check_name_building_unique = models.Constraint(
        'UNIQUE (name, building_id)',
        "Room name must be unique within the same building!",
    )

    name = fields.Char(string='Name', required=True)
    building_id = fields.Many2one('campus.building', string='Building', required=True)
    capacity = fields.Integer(string='Capacity', required=True)
    room_type = fields.Selection([
        ('theory', 'Theory'),
        ('lab', 'Laboratory')
    ], string='Room Type', required=True, default='theory')

    @api.constrains('capacity')
    def _check_capacity(self):
        for record in self:
            if record.capacity <= 0:
                raise ValidationError(_("Room capacity must be greater than zero."))
