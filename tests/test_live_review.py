from app.live_review import inverse_oras_live_change
from app.models import PendingChange, PendingRoleChange, PendingTeamChange, PendingTMTeach


def test_live_review_inverts_role_change():
    change = PendingRoleChange(
        pokemon_slot=1, pokemon="A", species="Species A",
        old_role="Mago", new_role="Tanque", pokemon_identity="pk-a",
    )
    inverse = inverse_oras_live_change(change)
    assert inverse.old_role == "Tanque"
    assert inverse.new_role == "Mago"
    assert inverse.pokemon_identity == "pk-a"


def test_live_review_inverts_tm_as_move_without_touching_bag():
    change = PendingTMTeach(
        role="Mago", pokemon_slot=2, pokemon="B", species="Species B",
        move_slot=3, old_move="Confusión", old_move_id=93,
        new_move="Lanzallamas", new_move_id=53, pokemon_identity="pk-b",
        item_id=350, tm_number=35, item_name="MT35", quantity_before=1,
    )
    inverse = inverse_oras_live_change(change)
    assert isinstance(inverse, PendingChange)
    assert inverse.old_move == "Lanzallamas"
    assert inverse.new_move == "Confusión"
    assert inverse.old_move_id == 53
    assert inverse.new_move_id == 93


def test_live_review_inverts_party_pc_swap():
    change = PendingTeamChange(
        operation="swap-party-box", party_slot=2, box=3, box_slot=7,
        outgoing_pokemon="Equipo", outgoing_species="A",
        incoming_pokemon="Caja", incoming_species="B", incoming_role="Tanque",
        incoming_snapshot={"role": "Tanque", "species_id": 2},
        outgoing_snapshot={"role": "Mago", "species_id": 1},
        incoming_identity="pc-b", outgoing_identity="party-a",
        box_witnesses=((8, "witness"),),
    )
    inverse = inverse_oras_live_change(change)
    assert isinstance(inverse, PendingTeamChange)
    assert inverse.outgoing_pokemon == "Caja"
    assert inverse.incoming_pokemon == "Equipo"
    assert inverse.incoming_role == "Mago"
    assert inverse.incoming_identity == "party-a"
    assert inverse.outgoing_identity == "pc-b"
    assert inverse.incoming_snapshot["species_id"] == 1
    assert inverse.outgoing_snapshot["species_id"] == 2
