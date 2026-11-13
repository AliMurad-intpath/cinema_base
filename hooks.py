from odoo import Command


def post_init_hook(env):
    """Give the administrator the Cinema Manager group on install."""
    manager = env.ref("cinema_base.group_cinema_manager")
    admin = env.ref("base.user_admin", raise_if_not_found=False)
    if admin:
        # The field was renamed between Odoo versions; support both spellings.
        field = "group_ids" if "group_ids" in admin._fields else "groups_id"
        admin.write({field: [Command.link(manager.id)]})
