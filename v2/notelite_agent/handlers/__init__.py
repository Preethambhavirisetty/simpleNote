HANDLERS = {
    "qdrant": "handlers.qdrant.QdrantHandler",
}


def get_handler(name):
    if name not in HANDLERS:
        supported = ", ".join(HANDLERS.keys())
        raise ValueError(f"Unsupported VECTOR_DB: '{name}'. Supported: {supported}")

    module_path, class_name = HANDLERS[name].rsplit(".", 1)
    module = __import__(module_path, fromlist=[class_name])
    handler_class = getattr(module, class_name)
    return handler_class()
