static int binarysearch1(const int *arr, int l, int r, int x)
{
    if (r >= l)
    {
        int mid = l + (r - l) / 2;

        // If element is present at middle
        if (arr[mid] == x)
            return mid;

        // If element is smaller than middle
        if (arr[mid] > x)
            return binarysearch1(arr, l, mid - 1, x);

        // Else element is in right subarray
        return binarysearch1(arr, mid + 1, r, x);
    }

    // When element is not present in array
    return -1;
}
