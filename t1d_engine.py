import math
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

HYPO_THRESHOLD = 70       # mg/dL
HYPER_THRESHOLD = 250     # mg/dL (Ketone warning threshold)
TIR_LOW = 70              # mg/dL
TIR_HIGH = 180            # mg/dL
VERY_LOW_THRESHOLD = 54   # mg/dL (Level 2 severe hypoglycemia)
VERY_HIGH_THRESHOLD = 250 # mg/dL

INSULIN_PEAKS = {
    'NovoRapid': 75,
    'Humalog': 75,
    'Apidra': 75,
    'Admelog': 75,
    'Fiasp': 55,
    'Lyumjev': 55,
}

CONTEXT_FACTORS = {
    'exercise': 0.8,  # -20%
    'sick': 1.2,      # +20%
    'stress': 1.1,    # +10%
}

# Unit conversions
def mg_dl_to_mmol_l(val: float) -> float:
    return round(val / 18.0182, 1)

def mmol_l_to_mg_dl(val: float) -> float:
    return round(val * 18.0182)

def format_bg(val: float, unit: str = "mg/dL") -> str:
    if unit == "mmol/L":
        return f"{mg_dl_to_mmol_l(val):.1f}"
    return f"{round(val)}"

def parse_bg_input(val: float, unit: str = "mg/dL") -> float:
    """Always converts incoming user input into internal mg/dL standard."""
    if unit == "mmol/L":
        return mmol_l_to_mg_dl(val)
    return float(val)

def iob_fraction(minutes: float, duration_hours: float, insulin_type: str) -> float:
    """
    Mudaliar exponential pharmacokinetic insulin action curve.
    Returns fraction (0.0 to 1.0) of active insulin remaining after `minutes`.
    """
    td = duration_hours * 60.0
    if minutes <= 0:
        return 1.0
    if minutes >= td:
        return 0.0

    peak = INSULIN_PEAKS.get(insulin_type, 75)
    tp = min(peak, td / 2.0 - 1.0)
    tau = (tp * (1.0 - tp / td)) / (1.0 - (2.0 * tp) / td)
    a = (2.0 * tau) / td
    S = 1.0 / (1.0 - a + (1.0 + a) * math.exp(-td / tau))
    t = minutes
    
    value = 1.0 - S * (1.0 - a) * (( (t * t) / (tau * td * (1.0 - a)) - t / tau - 1.0 ) * math.exp(-t / tau) + 1.0)
    return max(0.0, min(1.0, value))

def calculate_active_iob(
    doses: List[Dict[str, Any]],
    duration_hours: float = 4.0,
    insulin_type: str = "NovoRapid",
    reference_time: Optional[float] = None
) -> Tuple[float, List[Dict[str, Any]]]:
    """
    Calculates total active insulin on board across recent boluses.
    Returns (total_units, active_breakdown_list).
    """
    now = reference_time or time.time()
    total_iob = 0.0
    breakdown = []

    for d in doses:
        units = d.get("insulin_units")
        if not units or units <= 0:
            continue
        if d.get("spoiled_insulin"):
            continue  # ignore spoiled doses
        
        # Parse timestamp
        occurred_str = d.get("occurred_at")
        try:
            # Handle ISO timestamp
            dt = datetime.fromisoformat(occurred_str.replace("Z", "+00:00"))
            occurred_ts = dt.timestamp()
        except Exception:
            continue

        minutes_ago = (now - occurred_ts) / 60.0
        if 0 <= minutes_ago <= (duration_hours * 60.0):
            frac = iob_fraction(minutes_ago, duration_hours, insulin_type)
            active_units = units * frac
            if active_units > 0.01:
                total_iob += active_units
                breakdown.append({
                    "id": d.get("id"),
                    "occurred_at": occurred_str,
                    "original_units": units,
                    "active_units": round(active_units, 2),
                    "minutes_ago": round(minutes_ago, 1),
                    "remaining_fraction": round(frac, 3)
                })

    return round(total_iob, 2), breakdown

def round_dose(units: float, step: float = 0.5) -> float:
    if units <= 0:
        return 0.0
    return round(round(units / step) * step, 2)

def calculate_bolus(
    bg_mgdl: Optional[float],
    target_bg_mgdl: float,
    icr: Optional[float],
    isf: Optional[float],
    carbs: float,
    sugar: float,
    fat: float,
    current_iob: float,
    tags: List[str]
) -> Dict[str, Any]:
    """
    Clinical bolus calculator adhering to Type 1 Diabetes standards:
    - Meal bolus = carbs / ICR (sugar is already inside carbs)
    - Correction bolus = (BG - Target) / ISF
    - Active IOB is subtracted from correction dose to prevent insulin stacking
    - Context adjustment factors for exercise, illness, stress
    - High-fat protein split suggestion if fat > 20g
    - Hypo blocking guard if BG < 70 mg/dL
    """
    if bg_mgdl is not None and bg_mgdl < HYPO_THRESHOLD:
        return {
            "status": "blocked",
            "reason": "hypo",
            "message": "Blood glucose is below 70 mg/dL. Treat hypoglycemia first using the Rule of 15 before administering any insulin!"
        }

    # If blood glucose is elevated and user is calculating a correction, but ISF is not configured
    if bg_mgdl is not None and bg_mgdl > target_bg_mgdl and (not isf or isf <= 0) and carbs <= 0:
        return {
            "status": "missing_isf",
            "message": "Insulin Sensitivity Factor (ISF) is not configured in Settings. Please set your ISF to enable correction bolus calculations.",
            "target_bg": round(target_bg_mgdl, 1),
            "isf": None,
            "icr": icr,
            "active_iob": round(current_iob, 2),
            "meal_bolus": 0.0,
            "correction_bolus": 0.0,
            "total_units": 0.0,
            "recommended_dose": 0.0
        }

    meal_bolus = (carbs / icr) if (icr and icr > 0 and carbs > 0) else 0.0
    
    correction_bolus = 0.0
    if bg_mgdl is not None and isf and isf > 0:
        correction_bolus = (bg_mgdl - target_bg_mgdl) / isf

    # Context tag factor
    tag_factor = 1.0
    for t in tags:
        if t in CONTEXT_FACTORS:
            tag_factor *= CONTEXT_FACTORS[t]

    raw_before_iob = (meal_bolus + correction_bolus) * tag_factor
    raw_after_iob = max(0.0, raw_before_iob - current_iob)
    total_recommended = round_dose(raw_after_iob)

    # High fat/protein split bolus
    split = None
    if fat > 20.0 and meal_bolus > 0:
        upfront_fraction = 0.60
        adjusted_meal = meal_bolus * tag_factor
        upfront = round_dose(max(0.0, raw_after_iob - adjusted_meal * (1.0 - upfront_fraction)))
        later = round_dose(adjusted_meal * (1.0 - upfront_fraction))
        split = {
            "is_recommended": True,
            "upfront_units": upfront,
            "later_units": later,
            "later_delay_minutes": 120,
            "reason": f"High dietary fat ({round(fat)}g) delays gastric emptying and glucose absorption. Split 60% now, 40% in 2 hours."
        }

    return {
        "status": "ok",
        "meal_bolus": round(meal_bolus, 2),
        "correction_bolus": round(correction_bolus, 2),
        "target_bg": round(target_bg_mgdl, 1),
        "isf": isf,
        "icr": icr,
        "active_iob": round(current_iob, 2),
        "tag_factor": round(tag_factor, 2),
        "iob_subtracted": round(current_iob, 2),
        "raw_total": round(raw_after_iob, 2),
        "total_units": total_recommended,
        "recommended_dose": total_recommended,
        "requires_ketone_check": (bg_mgdl is not None and bg_mgdl > HYPER_THRESHOLD),
        "split_bolus": split
    }

def calculate_time_in_range(readings: List[Dict[str, Any]], max_gap_hours: float = 4.0) -> Dict[str, Any]:
    """
    Interpolates continuous time in range between blood glucose readings.
    Returns percentages for Very Low (<54), Low (54-70), Target (70-180), High (180-250), Very High (>250).
    """
    valid = []
    for r in readings:
        bg = r.get("bg_value")
        occ = r.get("occurred_at")
        if bg is not None and occ:
            try:
                ts = datetime.fromisoformat(occ.replace("Z", "+00:00")).timestamp()
                valid.append((ts, float(bg)))
            except Exception:
                pass

    if not valid:
        return {
            "count": 0, "very_low": 0, "low": 0, "in_range": 0, "high": 0, "very_high": 0,
            "mean_bg": 0, "estimated_a1c": None
        }

    valid.sort(key=lambda x: x[0])
    
    very_low = 0.0
    low = 0.0
    in_range = 0.0
    high = 0.0
    very_high = 0.0
    
    def classify(v: float, weight: float):
        nonlocal very_low, low, in_range, high, very_high
        if v < VERY_LOW_THRESHOLD:
            very_low += weight
        elif v < TIR_LOW:
            low += weight
        elif v <= TIR_HIGH:
            in_range += weight
        elif v <= VERY_HIGH_THRESHOLD:
            high += weight
        else:
            very_high += weight

    STEP = 5.0  # 5-minute sampling steps
    covered_minutes = 0.0
    for i in range(len(valid) - 1):
        t1, v1 = valid[i]
        t2, v2 = valid[i+1]
        diff_minutes = (t2 - t1) / 60.0
        if 0 < diff_minutes <= (max_gap_hours * 60.0):
            m = 0.0
            while m < diff_minutes:
                w = min(STEP, diff_minutes - m)
                interpolated_val = v1 + ((v2 - v1) * (m + w / 2.0)) / diff_minutes
                classify(interpolated_val, w)
                m += STEP
            covered_minutes += diff_minutes

    # If readings are sparse, fallback to discrete point count
    if covered_minutes == 0:
        for _, val in valid:
            classify(val, 1.0)
        total_weight = float(len(valid))
    else:
        total_weight = very_low + low + in_range + high + very_high

    pct = lambda w: round((w / total_weight) * 100, 1) if total_weight > 0 else 0.0
    
    all_vals = [v for _, v in valid]
    mean_bg = sum(all_vals) / len(all_vals)
    
    # Standard deviation / Glycemic Variability
    variance = sum((x - mean_bg) ** 2 for x in all_vals) / len(all_vals) if len(all_vals) > 1 else 0
    std_dev = math.sqrt(variance)
    cv = round((std_dev / mean_bg) * 100, 1) if mean_bg > 0 else 0

    # ADAG Estimated HbA1c equation: eA1c (%) = (mean_bg_mg_dl + 46.7) / 28.7
    ea1c_percent = round((mean_bg + 46.7) / 28.7, 1)
    # IFCC mmol/mol conversion: (eA1c - 2.15) * 10.929
    ea1c_mmol_mol = round((ea1c_percent - 2.15) * 10.929)

    return {
        "count": len(valid),
        "mean_bg": round(mean_bg, 1),
        "std_dev": round(std_dev, 1),
        "cv_percent": cv,
        "estimated_a1c": {
            "percent": ea1c_percent,
            "mmol_mol": ea1c_mmol_mol
        },
        "very_low": pct(very_low),
        "low": pct(low),
        "in_range": pct(in_range),
        "high": pct(high),
        "very_high": pct(very_high)
    }

def analyze_ratio_suggestions(
    entries: List[Dict[str, Any]],
    current_icr: Optional[float],
    current_isf: Optional[float]
) -> List[Dict[str, Any]]:
    """
    Audits meal logs and isolated corrections to suggest clinical ICR/ISF adjustments.
    """
    suggestions = []
    
    # Sort entries chronologically
    sorted_entries = []
    for e in entries:
        occ = e.get("occurred_at")
        if occ:
            try:
                ts = datetime.fromisoformat(occ.replace("Z", "+00:00")).timestamp()
                sorted_entries.append((ts, e))
            except Exception:
                pass
    sorted_entries.sort(key=lambda x: x[0])

    # 1. Post-meal spikes check (ICR)
    if current_icr and current_icr > 0:
        meal_bgs = []
        for i, (ts, e) in enumerate(sorted_entries):
            carbs = e.get("carbs")
            if carbs and carbs > 10 and e.get("insulin_units"):
                # Look for BG 90 to 180 min after meal
                for post_ts, post_e in sorted_entries[i+1:]:
                    diff_m = (post_ts - ts) / 60.0
                    if 90 <= diff_m <= 180 and post_e.get("bg_value"):
                        meal_bgs.append(post_e["bg_value"])
                        break

        if len(meal_bgs) >= 3:
            avg_post = sum(meal_bgs) / len(meal_bgs)
            if avg_post > TIR_HIGH:
                new_icr = max(1.0, round(current_icr * 0.9, 1))
                suggestions.append({
                    "id": "icr_spike",
                    "type": "ICR",
                    "title": "Post-Meal Glucose Consistently Spikes",
                    "description": f"Across {len(meal_bgs)} meals, your 2-hour post-meal blood glucose averaged {round(avg_post)} mg/dL (above the 180 mg/dL target). A stronger ratio will provide more insulin per gram of carbohydrates.",
                    "current": current_icr,
                    "suggested": new_icr,
                    "direction": "strengthen"
                })
            elif avg_post < 80:
                new_icr = round(current_icr * 1.1, 1)
                suggestions.append({
                    "id": "icr_hypo",
                    "type": "ICR",
                    "title": "Post-Meal Glucose Consistently Low",
                    "description": f"Across {len(meal_bgs)} meals, your 2-hour post-meal blood glucose averaged {round(avg_post)} mg/dL. A weaker ratio will provide safer, lower insulin doses for meals.",
                    "current": current_icr,
                    "suggested": new_icr,
                    "direction": "weaken"
                })

    # 2. Correction dose response check (ISF)
    if current_isf and current_isf > 0:
        correction_drops = []
        for i, (ts, e) in enumerate(sorted_entries):
            if e.get("dose_kind") == "correction" and e.get("insulin_units") and not e.get("carbs"):
                start_bg = e.get("bg_value")
                units = e.get("insulin_units")
                if start_bg and units and units > 0:
                    for post_ts, post_e in sorted_entries[i+1:]:
                        diff_h = (post_ts - ts) / 3600.0
                        if 2.0 <= diff_h <= 4.0 and post_e.get("bg_value"):
                            end_bg = post_e["bg_value"]
                            drop_per_unit = (start_bg - end_bg) / units
                            if drop_per_unit > 0:
                                correction_drops.append(drop_per_unit)
                            break
        
        if len(correction_drops) >= 3:
            observed_isf = sum(correction_drops) / len(correction_drops)
            if observed_isf < (current_isf * 0.75):
                new_isf = max(5.0, round((current_isf + observed_isf) / 2.0))
                suggestions.append({
                    "id": "isf_weak",
                    "type": "ISF",
                    "title": "Correction Boluses Underperforming",
                    "description": f"1 unit of insulin drops your glucose by {round(observed_isf)} mg/dL on average, less than your configured ISF of {current_isf} mg/dL.",
                    "current": current_isf,
                    "suggested": new_isf,
                    "direction": "strengthen"
                })
            elif observed_isf > (current_isf * 1.35):
                new_isf = round((current_isf + observed_isf) / 2.0)
                suggestions.append({
                    "id": "isf_strong",
                    "type": "ISF",
                    "title": "Correction Boluses Over-dropping Glucose",
                    "description": f"1 unit of insulin drops your glucose by {round(observed_isf)} mg/dL on average, substantially more than your configured ISF of {current_isf} mg/dL.",
                    "current": current_isf,
                    "suggested": new_isf,
                    "direction": "weaken"
                })

    return suggestions
