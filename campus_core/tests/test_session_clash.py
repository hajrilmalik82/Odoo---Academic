from datetime import datetime, timedelta

from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import TAG, CampusCommon


@tagged('post_install', '-at_install')
class TestSessionClash(CampusCommon):
    """Double-booking a single class session.

    academic.class.schedule refuses this for the weekly pattern, so generated
    sessions start out sound. The session form is editable all the same - a
    stand-in lecturer and a room change are both real needs - and nothing
    re-checked an edited one, so a meeting could be moved into an occupied
    room and the clash only surfaced at the door.
    """

    def setUp(self):
        super().setUp()
        self.start = datetime(2030, 3, 4, 8, 0)
        self.end = datetime(2030, 3, 4, 10, 0)
        self.other_room = self.env['campus.room'].create({
            'name': '%s B-202' % TAG, 'building_id': self.building.id,
            'capacity': 30, 'room_type': 'theory',
        })

    def _session(self, name='Sesi', room=None, lecturer=None, shift=0):
        return self.env['academic.class.session'].create({
            'name': '%s %s' % (TAG, name),
            'class_id': self.klass.id,
            'start_datetime': self.start + timedelta(hours=shift),
            'end_datetime': self.end + timedelta(hours=shift),
            'room_id': (room or self.room).id,
            'lecturer_id': lecturer.id if lecturer else False,
        })

    # --- the room -----------------------------------------------------------

    def test_two_sessions_cannot_share_a_room_at_the_same_time(self):
        self._session('Sesi 1')
        with self.assertRaises(ValidationError):
            self._session('Sesi 2')

    def test_the_refusal_names_the_room_and_the_other_session(self):
        """A clash is fixed by moving one of two meetings, so the message has
        to say which one is already there."""
        self._session('Sesi Awal')
        with self.assertRaises(ValidationError) as caught:
            self._session('Sesi Bentrok')
        message = str(caught.exception)
        self.assertIn(self.room.name, message)
        self.assertIn('Sesi Awal', message)

    def test_the_same_room_is_free_once_the_first_session_ends(self):
        self._session('Sesi Pagi')
        self._session('Sesi Siang', shift=2)

    def test_another_room_at_the_same_time_is_fine(self):
        self._session('Sesi Pagi')
        self._session('Sesi Paralel', room=self.other_room)

    def test_moving_a_session_into_an_occupied_room_is_refused(self):
        """The write path, not just create: this is the edit the constraint
        exists for."""
        self._session('Sesi Tetap')
        moved = self._session('Sesi Pindah', room=self.other_room)
        with self.assertRaises(ValidationError):
            moved.room_id = self.room

    # --- the lecturer -------------------------------------------------------

    def test_one_lecturer_cannot_be_in_two_places_at_once(self):
        self._session('Sesi 1', lecturer=self.advisor)
        with self.assertRaises(ValidationError):
            self._session('Sesi 2', room=self.other_room, lecturer=self.advisor)

    def test_a_session_with_no_lecturer_yet_clashes_with_nobody(self):
        """campus_core generates the timetable before campus_employees says who
        teaches it, so an empty lecturer is the ordinary starting state."""
        self._session('Sesi 1')
        self._session('Sesi 2', room=self.other_room)

    # --- batches ------------------------------------------------------------

    def test_two_sessions_created_in_one_batch_are_compared_with_each_other(self):
        """A per-record search against the table only ever sees rows already
        committed, so a single import could place two meetings in one room."""
        with self.assertRaises(ValidationError):
            self.env['academic.class.session'].create([
                {
                    'name': '%s Batch 1' % TAG, 'class_id': self.klass.id,
                    'start_datetime': self.start, 'end_datetime': self.end,
                    'room_id': self.room.id,
                },
                {
                    'name': '%s Batch 2' % TAG, 'class_id': self.klass.id,
                    'start_datetime': self.start, 'end_datetime': self.end,
                    'room_id': self.room.id,
                },
            ])

    def test_generating_a_term_of_sessions_still_works(self):
        """Fourteen weekly meetings in one room must not read as fourteen
        clashes with each other."""
        self.klass.action_generate_sessions()
        self.assertTrue(self.klass.session_ids)
