from __future__ import annotations

from collections import Counter
import re

from ...normalizers.currency import resolve_country_code
from .invoice_cleaner import normalize_hs_code

_SERVICE_DESCRIPTION_HINTS = (
    "fracht",
    "freight",
    "shipping",
    "delivery",
    "transport",
    "handling",
    "service",
    "charge",
    "logistic",
    "достав",
    "перевоз",
    "фрахт",
    "услуг",
)


def _has_cyrillic(value) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", str(value or "")))


def _has_latin(value) -> bool:
    return bool(re.search(r"[A-Za-z]", str(value or "")))


def _looks_like_service_charge_description(value) -> bool:
    description = str(value or "").strip().lower()
    if not description:
        return False
    return any(hint in description for hint in _SERVICE_DESCRIPTION_HINTS)


def _harmonize_position_groups(items: list[dict]) -> list[dict]:
    if not items:
        return items

    def _raw_position(item: dict) -> int | None:
        raw_pos = item.get("position")
        try:
            return int(raw_pos) if raw_pos is not None else None
        except (TypeError, ValueError):
            return None

    def _norm_hs(value) -> str | None:
        text = str(value or "").strip()
        return text or None

    def _norm_text(value) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    def _country_is_valid(value) -> bool:
        return resolve_country_code(str(value or "").strip()) is not None

    hs_frequency: dict[str, int] = {}
    for item in items:
        hs_code = _norm_hs(item.get("hs_code"))
        if hs_code is not None:
            hs_frequency[hs_code] = hs_frequency.get(hs_code, 0) + 1

    by_position: dict[int, list[dict]] = {}
    for item in items:
        position = _raw_position(item)
        if position is not None:
            by_position.setdefault(position, []).append(item)

    for position_items in by_position.values():
        by_description: dict[str, list[dict]] = {}
        for item in position_items:
            description_key = _norm_text(item.get("description"))
            if description_key:
                by_description.setdefault(description_key, []).append(item)

        for rows in by_description.values():
            valid_countries = [
                str(row.get("country_origin")).strip()
                for row in rows
                if _country_is_valid(row.get("country_origin"))
            ]
            if valid_countries:
                dominant_country = max(set(valid_countries), key=valid_countries.count)
                for row in rows:
                    if not _country_is_valid(row.get("country_origin")):
                        row["country_origin"] = dominant_country

            group_hs: dict[str, int] = {}
            for row in rows:
                hs_code = _norm_hs(row.get("hs_code"))
                if hs_code is not None:
                    group_hs[hs_code] = group_hs.get(hs_code, 0) + 1
            if not group_hs:
                continue

            dominant_hs = max(
                group_hs,
                key=lambda hs: (group_hs[hs], hs_frequency.get(hs, 0), len(hs)),
            )
            dominant_global = hs_frequency.get(dominant_hs, 0)

            for row in rows:
                current_hs = _norm_hs(row.get("hs_code"))
                if current_hs is None:
                    row["hs_code"] = dominant_hs
                    continue
                if current_hs == dominant_hs:
                    continue
                current_global = hs_frequency.get(current_hs, 0)
                if dominant_global < 2 and group_hs.get(dominant_hs, 0) < 2:
                    continue
                if current_global >= dominant_global:
                    continue
                row["hs_code"] = dominant_hs

    return items


def _enrich_from_position_peers(items: list[dict]) -> list[dict]:
    if not items:
        return items

    def _raw_position(item: dict) -> int | None:
        raw_pos = item.get("position")
        try:
            return int(raw_pos) if raw_pos is not None else None
        except (TypeError, ValueError):
            return None

    def _is_empty(value) -> bool:
        return value is None or str(value).strip().lower() in {"", "null", "none"}

    def _norm_num(value, decimals: int = 4) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed <= 0:
            return None
        return round(parsed, decimals)

    def _norm_hs(value) -> str | None:
        normalized = normalize_hs_code(value)
        return normalized or None

    def _norm_text(value) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    def _description_words(value) -> set[str]:
        return {
            token
            for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", _norm_text(value))
            if len(token) >= 3
        }

    def _descriptions_are_close(a, b) -> bool:
        a_words = _description_words(a)
        b_words = _description_words(b)
        if not a_words or not b_words:
            return False
        overlap = len(a_words & b_words)
        shortest = min(len(a_words), len(b_words))
        return overlap >= 2 and overlap >= shortest - 1

    def _dominant(values: list):
        cleaned = [value for value in values if value is not None]
        if not cleaned:
            return None
        counts = Counter(cleaned).most_common()
        if len(counts) == 1:
            return counts[0][0]
        if counts[0][1] > counts[1][1] and counts[0][1] >= 2:
            return counts[0][0]
        return None

    by_position: dict[int, list[dict]] = {}
    for item in items:
        position = _raw_position(item)
        if position is not None:
            by_position.setdefault(position, []).append(item)

    for rows in by_position.values():
        dominant_country = _dominant(
            [
                str(row.get("country_origin")).strip()
                for row in rows
                if resolve_country_code(str(row.get("country_origin") or "").strip()) is not None
            ]
        )
        dominant_hs = _dominant([_norm_hs(row.get("hs_code")) for row in rows])
        dominant_qty = _dominant([_norm_num(row.get("quantity"), 3) for row in rows])
        dominant_cost = _dominant([_norm_num(row.get("cost")) for row in rows])
        dominant_price = _dominant([_norm_num(row.get("price")) for row in rows])

        for row in rows:
            hydrated = bool(row.get("_peer_hydrated"))

            if _is_empty(row.get("hs_code")):
                decl_hs = _norm_hs(row.get("_decl_ref"))
                if decl_hs is not None:
                    row["hs_code"] = decl_hs
                    hydrated = True

            if _is_empty(row.get("country_origin")) and dominant_country is not None:
                row["country_origin"] = dominant_country
                hydrated = True

            if _is_empty(row.get("hs_code")) and dominant_hs is not None:
                row["hs_code"] = dominant_hs
                hydrated = True

            if _is_empty(row.get("quantity")) and dominant_qty is not None:
                row["quantity"] = dominant_qty
                hydrated = True

            if _is_empty(row.get("cost")) and dominant_cost is not None:
                row["cost"] = dominant_cost
                hydrated = True

            quantity = _norm_num(row.get("quantity"), 3)
            cost = _norm_num(row.get("cost"))
            price = _norm_num(row.get("price"))

            if price is None and quantity is not None and cost is not None:
                row["price"] = round(quantity * cost, 4)
                hydrated = True
                price = _norm_num(row.get("price"))

            if _is_empty(row.get("price")) and price is None and dominant_price is not None:
                row["price"] = dominant_price
                hydrated = True
                price = _norm_num(row.get("price"))

            if _is_empty(row.get("cost")) and cost is None and quantity is not None and price is not None and quantity > 0:
                row["cost"] = round(price / quantity, 4)
                hydrated = True

            if _is_empty(row.get("hs_code")):
                close_peers = []
                for peer in rows:
                    if peer is row:
                        continue
                    peer_hs = _norm_hs(peer.get("hs_code"))
                    if peer_hs is None:
                        continue
                    peer_qty = _norm_num(peer.get("quantity"), 3)
                    peer_cost = _norm_num(peer.get("cost"))
                    peer_price = _norm_num(peer.get("price"))
                    if quantity is not None and peer_qty is not None and quantity != peer_qty:
                        continue
                    if cost is not None and peer_cost is not None and cost != peer_cost:
                        continue
                    if price is not None and peer_price is not None and price != peer_price:
                        continue
                    if not _descriptions_are_close(row.get("description"), peer.get("description")):
                        continue
                    close_peers.append(peer)

                if len(close_peers) == 1:
                    peer = close_peers[0]
                    row["hs_code"] = peer.get("hs_code")
                    if _is_empty(row.get("country_origin")) and not _is_empty(peer.get("country_origin")):
                        row["country_origin"] = peer.get("country_origin")
                    hydrated = True

            if not _has_cyrillic(row.get("description")):
                descriptive_peers = []
                for peer in rows:
                    if peer is row:
                        continue
                    if not _has_cyrillic(peer.get("description")):
                        continue
                    peer_qty = _norm_num(peer.get("quantity"), 3)
                    peer_cost = _norm_num(peer.get("cost"))
                    peer_price = _norm_num(peer.get("price"))
                    if quantity is not None and peer_qty is not None and quantity != peer_qty:
                        continue
                    if cost is not None and peer_cost is not None and cost != peer_cost:
                        continue
                    if price is not None and peer_price is not None and price != peer_price:
                        continue
                    if len(re.sub(r"[^\wА-Яа-яЁё]", "", str(peer.get("description") or ""))) <= len(
                        re.sub(r"[^\wА-Яа-яЁё]", "", str(row.get("description") or ""))
                    ):
                        continue
                    descriptive_peers.append(peer)

                if len(descriptive_peers) == 1:
                    peer = descriptive_peers[0]
                    row["description"] = peer.get("description")
                    if _is_empty(row.get("country_origin")) and not _is_empty(peer.get("country_origin")):
                        row["country_origin"] = peer.get("country_origin")
                    if _is_empty(row.get("hs_code")) and not _is_empty(peer.get("hs_code")):
                        row["hs_code"] = peer.get("hs_code")
                    hydrated = True

            if _has_cyrillic(row.get("description")) and _has_latin(row.get("description")):
                richer_cyrillic_peers = []
                row_compact = re.sub(r"[^\wА-Яа-яЁё]", "", str(row.get("description") or ""))
                for peer in rows:
                    if peer is row:
                        continue
                    peer_description = str(peer.get("description") or "")
                    if not _has_cyrillic(peer_description) or _has_latin(peer_description):
                        continue
                    peer_qty = _norm_num(peer.get("quantity"), 3)
                    peer_cost = _norm_num(peer.get("cost"))
                    peer_price = _norm_num(peer.get("price"))
                    if quantity is not None and peer_qty is not None and quantity != peer_qty:
                        continue
                    if cost is not None and peer_cost is not None and cost != peer_cost:
                        continue
                    if price is not None and peer_price is not None and price != peer_price:
                        continue
                    peer_compact = re.sub(r"[^\wА-Яа-яЁё]", "", peer_description)
                    if len(peer_compact) <= len(row_compact) + 6:
                        continue
                    richer_cyrillic_peers.append(peer)

                if len(richer_cyrillic_peers) == 1:
                    peer = richer_cyrillic_peers[0]
                    row["description"] = peer.get("description")
                    if _is_empty(row.get("country_origin")) and not _is_empty(peer.get("country_origin")):
                        row["country_origin"] = peer.get("country_origin")
                    if _is_empty(row.get("hs_code")) and not _is_empty(peer.get("hs_code")):
                        row["hs_code"] = peer.get("hs_code")
                    hydrated = True

            if hydrated:
                row["_peer_hydrated"] = True

    return items


def _prune_shadow_rows(items: list[dict]) -> list[dict]:
    if not items:
        return items

    def _raw_position(item: dict) -> int | None:
        raw_pos = item.get("position")
        try:
            return int(raw_pos) if raw_pos is not None else None
        except (TypeError, ValueError):
            return None

    def _norm_num(value, decimals: int = 2) -> float:
        try:
            return round(float(value or 0), decimals)
        except (TypeError, ValueError):
            return 0.0

    def _norm_hs(value) -> str | None:
        text = str(value or "").strip()
        return text or None

    def _norm_text(value) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    def _country_is_valid(value) -> bool:
        return resolve_country_code(str(value or "").strip()) is not None

    def _line_sig_first(item: dict) -> str | None:
        line_sig = item.get("_line_sig")
        if isinstance(line_sig, tuple) and line_sig:
            return str(line_sig[0]).strip()
        return None

    def _line_sig_token(item: dict, index: int) -> str | None:
        line_sig = item.get("_line_sig")
        if isinstance(line_sig, tuple) and len(line_sig) > index:
            return str(line_sig[index]).strip()
        return None

    def _line_sig_has_repeated_country_token(item: dict) -> bool:
        line_sig = item.get("_line_sig")
        if not isinstance(line_sig, tuple):
            return False
        return any(
            re.fullmatch(r"([a-z]{2})\s+\1", str(token or "").strip().lower()) is not None
            for token in line_sig[:5]
        )

    def _part_no_key(item: dict) -> str | None:
        digits = re.sub(r"\D", "", str(item.get("part_no") or ""))
        return digits or None

    def _country_key(value):
        text = str(value or "").strip()
        if not text:
            return None
        repeated_codes = re.fullmatch(r"([A-Za-z]{2})\s+\1", text, re.IGNORECASE)
        if repeated_codes:
            text = repeated_codes.group(1).upper()
        resolved = resolve_country_code(text)
        if resolved is not None:
            return str(resolved)
        compact = re.sub(r"[^A-Za-z]", "", text).upper()
        resolved = resolve_country_code(compact) if compact else None
        if resolved is not None:
            return str(resolved)
        return text.lower()

    def _digit_hamming_distance(a: int | None, b: int | None) -> int | None:
        if a is None or b is None:
            return None
        a_digits = str(a)
        b_digits = str(b)
        if len(a_digits) != len(b_digits):
            return None
        return sum(ch_a != ch_b for ch_a, ch_b in zip(a_digits, b_digits))

    def _close(a: float, b: float, *, rel: float = 0.02, abs_tol: float = 1.0) -> bool:
        if a <= 0 or b <= 0:
            return False
        return abs(a - b) <= max(abs_tol, rel * max(a, b))

    def _quality(item: dict) -> int:
        score = 0
        description = str(item.get("description") or "").strip()
        if _norm_hs(item.get("hs_code")) is not None:
            score += 3
        if _country_is_valid(item.get("country_origin")):
            score += 1
        if _has_cyrillic(description):
            score += 2
        if len(re.sub(r"[^\wА-Яа-яЁё]", "", description)) >= 8:
            score += 1
        if re.fullmatch(r"[A-Za-z ]+", description) and description == description.lower():
            score -= 1
        if description and re.fullmatch(r"[A-Za-z0-9 .,'\"()/-]+", description) and not _has_cyrillic(description):
            score -= 1
        return score

    def _is_zero_value_service_row(item: dict, description: str) -> bool:
        compact_description = re.sub(r"[^\wА-Яа-яЁё]", "", description)
        if len(compact_description) < 5:
            return False
        quantity = _norm_num(item.get("quantity"), 3)
        cost = _norm_num(item.get("cost"))
        price = _norm_num(item.get("price"))
        return quantity > 0 and abs(cost) <= 0.001 and abs(price) <= 0.001

    def _collapse_group_score(item: dict) -> tuple[int, int, int]:
        score = _quality(item) * 10
        description = str(item.get("description") or "").strip()
        compact_description = re.sub(r"[^\wА-Яа-яЁё]", "", description)
        lower_description = description.lower()
        quantity = _norm_num(item.get("quantity"), 3)
        cost = _norm_num(item.get("cost"))
        price = _norm_num(item.get("price"))
        part_no = _part_no_key(item)
        hs_code = _norm_hs(item.get("hs_code"))

        if part_no:
            score += 5
            if part_no == "000000":
                score -= 8
        else:
            score -= 4
        if hs_code is not None:
            score += 4
        if _country_is_valid(item.get("country_origin")):
            score += 3
        if _has_cyrillic(description):
            score += 4
        score += min(8, len(compact_description) // 6)
        if quantity > 0 and cost > 0 and price > 0:
            expected_total = quantity * cost
            if _close(price, expected_total, rel=0.03, abs_tol=1.0):
                score += 5
            elif abs(price - expected_total) > max(5.0, 0.15 * max(price, expected_total)):
                score -= 5

        if re.search(r"(?:state of state|limite|onto|yomal|710my)", lower_description):
            score -= 10
        if re.search(r"[=•_]", description):
            score -= 5

        line_sig = item.get("_line_sig")
        if isinstance(line_sig, tuple):
            score -= max(0, len(line_sig) - 9)
            score -= sum(
                1
                for token in line_sig
                if re.fullmatch(r"[•=,_\-. ]+", str(token or "").strip() or " ") is not None
            )

        return score, len(compact_description), 1 if _has_cyrillic(description) else 0

    canonical_by_position: dict[int, list[dict]] = {}
    rows_by_position: dict[int, list[dict]] = {}
    for item in items:
        pos = _raw_position(item)
        if pos is None:
            continue
        rows_by_position.setdefault(pos, []).append(item)
        if _norm_hs(item.get("hs_code")) is None:
            continue
        canonical_by_position.setdefault(pos, []).append(item)

    keep = [True] * len(items)
    for idx, item in enumerate(items):
        position = _raw_position(item)
        description = str(item.get("description") or "").strip()
        line_sig_first = _line_sig_first(item)

        if (
            position is None
            and line_sig_first in {"0", "000000"}
            and description
            and not _has_cyrillic(description)
        ):
            keep[idx] = False
            continue

        if position is not None and 0 < position <= 500:
            current_qty = _norm_num(item.get("quantity"), 3)
            current_cost = _norm_num(item.get("cost"))
            current_price = _norm_num(item.get("price"))
            current_country = _country_key(item.get("country_origin"))
            current_desc = _norm_text(description)
            current_hint = _norm_text(_line_sig_token(item, 1))
            current_part_no = _part_no_key(item)

            if current_part_no is not None:
                peer_candidates = []
            else:
                peer_candidates = []
                for candidate in items:
                    candidate_pos = _raw_position(candidate)
                    if candidate is item or candidate_pos is None or candidate_pos <= 1000:
                        continue
                    candidate_cost = _norm_num(candidate.get("cost"))
                    if not _close(current_cost, candidate_cost, rel=0.03, abs_tol=0.05):
                        continue
                    candidate_country = _country_key(candidate.get("country_origin"))
                    if current_country is not None and candidate_country not in {None, current_country}:
                        continue
                    candidate_desc = _norm_text(candidate.get("description"))
                    candidate_hint = _norm_text(_line_sig_token(candidate, 1))
                    if not any(
                        (
                            current_desc and current_desc == candidate_desc,
                            current_hint and current_hint == candidate_hint,
                            current_hint and current_hint == candidate_desc,
                        )
                    ):
                        continue
                    if current_qty > 0:
                        candidate_qty = _norm_num(candidate.get("quantity"), 3)
                        candidate_price = _norm_num(candidate.get("price"))
                        if not (
                            current_qty == candidate_qty
                            or _close(current_price, candidate_price, rel=0.03, abs_tol=1.0)
                        ):
                            if not (current_cost > 0 and candidate_cost > 0):
                                continue
                    peer_candidates.append(candidate)

            if current_part_no is not None:
                peer_candidates = [
                    candidate
                    for candidate in peer_candidates
                    if str(int(candidate["position"])) != current_part_no
                ]

            peer_positions = {
                int(candidate["position"])
                for candidate in peer_candidates
                if candidate.get("position") is not None
            }
            if len(peer_positions) == 1:
                peer = peer_candidates[0]
                item["position"] = peer["position"]
                if _has_cyrillic(str(peer.get("description") or "")) and not _has_cyrillic(description):
                    item["description"] = peer.get("description")
                if _norm_hs(item.get("hs_code")) is None and _norm_hs(peer.get("hs_code")) is not None:
                    item["hs_code"] = peer.get("hs_code")
                if not _country_is_valid(item.get("country_origin")) and _country_is_valid(peer.get("country_origin")):
                    item["country_origin"] = peer.get("country_origin")
                position = _raw_position(item)
                current_desc = _norm_text(item.get("description"))

            if not peer_candidates:
                looks_garbled = bool(re.search(r"[=]|\d", description)) or len(re.findall(r"[A-Za-zА-Яа-яЁё]{2,}", description)) < 2
                if (
                    not _is_zero_value_service_row(item, description)
                    and (
                    current_part_no is None
                    and not _has_cyrillic(description)
                    and not _country_is_valid(item.get("country_origin"))
                    and not _looks_like_service_charge_description(description)
                    and looks_garbled
                    )
                ):
                    keep[idx] = False
                    continue

        if position is not None and position > 1000:
            for neighbor_idx, neighbor in enumerate(items):
                if neighbor_idx == idx or not keep[neighbor_idx]:
                    continue
                neighbor_pos = _raw_position(neighbor)
                if neighbor_pos is None or not (0 < neighbor_pos <= 500):
                    continue
                if _part_no_key(neighbor) != str(position):
                    continue
                current_qty = _norm_num(item.get("quantity"), 3)
                current_cost = _norm_num(item.get("cost"))
                current_price = _norm_num(item.get("price"))
                neighbor_qty = _norm_num(neighbor.get("quantity"), 3)
                neighbor_cost = _norm_num(neighbor.get("cost"))
                neighbor_price = _norm_num(neighbor.get("price"))
                if current_qty > 0 and neighbor_qty > 0 and current_qty != neighbor_qty:
                    continue
                if current_cost > 0 and neighbor_cost > 0 and not _close(current_cost, neighbor_cost, rel=0.03, abs_tol=0.05):
                    continue
                if current_price > 0 and neighbor_price > 0 and not _close(current_price, neighbor_price, rel=0.03, abs_tol=1.0):
                    continue
                keep[idx] = False
                break
            if not keep[idx]:
                continue

        if (
            position is not None
            and _norm_hs(item.get("hs_code")) is None
            and position in canonical_by_position
        ):
            quantity = _norm_num(item.get("quantity"), 3)
            price = _norm_num(item.get("price"))
            for canonical in canonical_by_position[position]:
                if quantity <= 0 or quantity != _norm_num(canonical.get("quantity"), 3):
                    continue
                canonical_price = _norm_num(canonical.get("price"))
                canonical_cost = _norm_num(canonical.get("cost"))
                if not (
                    _close(price, canonical_price, rel=0.02, abs_tol=1.0)
                    or _close(price, canonical_cost, rel=0.02, abs_tol=1.0)
                ):
                    continue
                if _quality(item) < _quality(canonical):
                    keep[idx] = False
                    break
            if not keep[idx]:
                continue

        if position is not None and position in rows_by_position:
            current_qty = _norm_num(item.get("quantity"), 3)
            current_cost = _norm_num(item.get("cost"))
            current_price = _norm_num(item.get("price"))
            current_quality = _quality(item)
            for candidate in rows_by_position[position]:
                if candidate is item:
                    continue
                candidate_quality = _quality(candidate)
                if candidate_quality < current_quality + 2:
                    continue
                candidate_qty = _norm_num(candidate.get("quantity"), 3)
                if current_qty <= 0 or current_qty != candidate_qty:
                    continue
                candidate_cost = _norm_num(candidate.get("cost"))
                candidate_price = _norm_num(candidate.get("price"))
                numerically_equivalent = (
                    _close(current_price, candidate_price, rel=0.03, abs_tol=1.0)
                    or (
                        _close(current_cost, candidate_cost, rel=0.03, abs_tol=0.05)
                        and _close(current_price, candidate_price, rel=0.03, abs_tol=1.0)
                    )
                    or _close(current_price, candidate_cost, rel=0.03, abs_tol=1.0)
                )
                if not numerically_equivalent:
                    continue
                candidate_description = str(candidate.get("description") or "").strip()
                current_country_valid = _country_is_valid(item.get("country_origin"))
                candidate_country_valid = _country_is_valid(candidate.get("country_origin"))
                if (
                    _norm_hs(item.get("hs_code")) is None
                    or (not current_country_valid and candidate_country_valid)
                    or (not _has_cyrillic(description) and _has_cyrillic(candidate_description))
                    or candidate_quality >= current_quality + 3
                ):
                    keep[idx] = False
                    break
            if not keep[idx]:
                continue

            for candidate in rows_by_position[position]:
                if candidate is item:
                    continue
                candidate_quality = _quality(candidate)
                if candidate_quality <= current_quality:
                    continue
                candidate_qty = _norm_num(candidate.get("quantity"), 3)
                candidate_cost = _norm_num(candidate.get("cost"))
                candidate_price = _norm_num(candidate.get("price"))
                candidate_description = str(candidate.get("description") or "").strip()
                if current_qty <= 1 or candidate_qty is None or candidate_qty <= 0:
                    continue
                if not _close(current_price, candidate_price, rel=0.03, abs_tol=1.0):
                    continue
                if not _close(candidate_cost, candidate_price, rel=0.02, abs_tol=1.0):
                    continue
                if not _close(current_cost * current_qty, current_price, rel=0.03, abs_tol=1.0):
                    continue
                if _has_cyrillic(description):
                    continue
                if not (_has_cyrillic(candidate_description) or len(candidate_description) > len(description)):
                    continue
                keep[idx] = False
                break
            if not keep[idx]:
                continue

        if (
            position is not None
            and 0 < position <= 500
            and line_sig_first == str(position)
            and description
            and not _has_cyrillic(description)
            and _line_sig_has_repeated_country_token(item)
        ):
            current_qty = _norm_num(item.get("quantity"), 3)
            current_cost = _norm_num(item.get("cost"))
            current_country = _country_key(item.get("country_origin"))
            current_desc = _norm_text(description)
            for neighbor_idx, neighbor in enumerate(items):
                if neighbor_idx == idx or not keep[neighbor_idx]:
                    continue
                neighbor_pos = _raw_position(neighbor)
                if neighbor_pos is None or neighbor_pos <= 1000:
                    continue
                if _norm_text(neighbor.get("description")) != current_desc:
                    continue
                if current_qty <= 0 or current_qty != _norm_num(neighbor.get("quantity"), 3):
                    continue
                if not _close(current_cost, _norm_num(neighbor.get("cost")), rel=0.03, abs_tol=0.05):
                    continue
                neighbor_country = _country_key(neighbor.get("country_origin"))
                if current_country is not None and neighbor_country not in {None, current_country}:
                    continue
                keep[idx] = False
                break

        if (
            keep[idx]
            and position is not None
            and _norm_hs(item.get("hs_code")) is None
            and len(re.sub(r"[^\wА-Яа-яЁё]", "", description)) <= 4
            and _part_no_key(item) is None
        ):
            current_qty = _norm_num(item.get("quantity"), 3)
            for neighbor_idx, neighbor in enumerate(items):
                if neighbor_idx == idx or not keep[neighbor_idx]:
                    continue
                neighbor_pos = _raw_position(neighbor)
                if _norm_hs(neighbor.get("hs_code")) is None:
                    continue
                if _digit_hamming_distance(position, neighbor_pos) != 1:
                    continue
                if current_qty <= 0 or current_qty != _norm_num(neighbor.get("quantity"), 3):
                    continue
                neighbor_description = str(neighbor.get("description") or "").strip()
                if len(re.sub(r"[^\wА-Яа-яЁё]", "", neighbor_description)) <= len(
                    re.sub(r"[^\wА-Яа-яЁё]", "", description)
                ) + 4:
                    continue
                keep[idx] = False
                break

    survivors = [item for item, keep_item in zip(items, keep) if keep_item]

    by_position: dict[int, list[tuple[int, dict]]] = {}
    for idx, item in enumerate(survivors):
        position = _raw_position(item)
        if position is None:
            continue
        by_position.setdefault(position, []).append((idx, item))

    collapsed: list[dict] = []
    consumed_indexes: set[int] = set()
    for idx, item in enumerate(survivors):
        if idx in consumed_indexes:
            continue

        position = _raw_position(item)
        if position is None or position > 500:
            collapsed.append(item)
            continue

        group = by_position.get(position, [])
        if len(group) <= 1:
            collapsed.append(item)
            continue

        best_idx, best_item = max(
            group,
            key=lambda pair: (_collapse_group_score(pair[1]), -pair[0]),
        )
        collapsed.append(best_item)
        consumed_indexes.update(group_idx for group_idx, _ in group)

    large_position_rows = []
    small_position_rows = []
    for item in collapsed:
        position = _raw_position(item)
        if position is None:
            continue
        if position > 1000:
            large_position_rows.append(item)
        elif 0 < position <= 500:
            small_position_rows.append(item)

    final_items: list[dict] = []
    for item in collapsed:
        position = _raw_position(item)
        if position is None or position <= 1000:
            final_items.append(item)
            continue

        current_qty = _norm_num(item.get("quantity"), 3)
        current_cost = _norm_num(item.get("cost"))
        current_price = _norm_num(item.get("price"))
        current_country = _country_key(item.get("country_origin"))
        duplicate_shadow = False
        for neighbor in small_position_rows:
            neighbor_qty = _norm_num(neighbor.get("quantity"), 3)
            neighbor_cost = _norm_num(neighbor.get("cost"))
            neighbor_price = _norm_num(neighbor.get("price"))
            neighbor_country = _country_key(neighbor.get("country_origin"))
            if current_country is not None and neighbor_country not in {None, current_country}:
                continue
            if current_qty > 0 and neighbor_qty > 0 and current_qty != neighbor_qty:
                continue
            if current_cost > 0 and neighbor_cost > 0 and not _close(current_cost, neighbor_cost, rel=0.03, abs_tol=0.05):
                continue
            if current_price > 0 and neighbor_price > 0 and not _close(current_price, neighbor_price, rel=0.03, abs_tol=1.0):
                continue
            duplicate_shadow = True
            break

        if not duplicate_shadow:
            final_items.append(item)

    return final_items
