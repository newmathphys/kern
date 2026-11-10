static const unsigned long long MAX_SIZE = 1000000;
static void prime(int *p)
{
	for(long long int i=3;i<=MAX_SIZE;i+=2) { p[i]=1; }
	for(long long int i=3;i<=MAX_SIZE;i+=2)
	{
		if(p[i]==1) {
		    for(long long int j=i*i;j<=MAX_SIZE;j+=i) {
			p[j]=0;
		    }
		}
	}
	p[2]=1;
	p[0]=p[1]=0;    
}
/**
 * @brief Count func counts the number of 
 * prime numbers.
 * @param arr contains the prime numbers
 * @param size denotes upto which prime numbers are to be found out
 * @returns count of prime numbers
 */
static int count(int *arr, const int size){
  int k=0;
  for(int i=0;i<=size;i++){
    if(arr[i]==1){
      k++;
    }
  }
  return k;
}
