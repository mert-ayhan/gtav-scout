"""Conservative render signal metrics; no semantic or quality classification."""
def pixel_signal(pixels,channels=4):
    if channels<3 or len(pixels)<channels or len(pixels)%channels:
        raise ValueError('Complete RGB/RGBA pixels required')
    count=len(pixels)//channels
    ordered=[sorted(pixels[c::channels]) for c in range(3)]
    ranges=[float(values[-1]-values[0]) for values in ordered]
    central_ranges=[float(values[min(count-1,count*99//100)]-values[count//100]) for values in ordered]
    background=tuple(values[count//2] for values in ordered)
    foreground=sum(any(abs(pixels[i+c]-background[c])>.02 for c in range(3)) for i in range(0,len(pixels),channels))
    return {'rgb_ranges':ranges,'central_98_percent_ranges':central_ranges,'foreground_fraction_vs_median':foreground/count,
            'uniform':max(ranges)<=1e-6,'low_signal':foreground/count<.001 or max(ranges)<.04 and max(central_ranges)<.01,
            'interpretation':'Technical signal only. Low signal can be a thin or low-contrast valid object; inspect it.'}
