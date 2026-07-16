from image_utils import normalize_image_url, parse_image_list


def is_persisted_image_url(image: str) -> bool:
    normalized = normalize_image_url(image)
    return normalized.startswith(("http://", "https://", "/uploads/", "/media/"))


def sanitize_work_images(image, images) -> tuple[str, list[str]]:
    """Drop browser-local URLs and return a durable primary image plus image list."""
    candidates = [normalize_image_url(image), *parse_image_list(images)]
    durable: list[str] = []
    for candidate in candidates:
        normalized = normalize_image_url(candidate)
        if is_persisted_image_url(normalized) and normalized not in durable:
            durable.append(normalized)
    return (durable[0] if durable else ""), durable
