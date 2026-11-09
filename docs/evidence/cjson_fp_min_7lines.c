int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size)
    if(data[size-1] != '\0') return 0;
    if(data[0] != '1' && data[0] != '0') return 0;
    if(data[1] != '1' && data[1] != '0') return 0;
    if(data[2] != '1' && data[2] != '0') return 0;
    json = cJSON_ParseWithOpts((const char*)data + offset, NULL, require_termination);
    if(json == NULL) return 0;
