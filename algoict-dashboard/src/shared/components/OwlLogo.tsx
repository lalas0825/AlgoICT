import Image from 'next/image';

export default function OwlLogo({ size = 'sm' }: { size?: 'sm' | 'lg' }) {
  const h = size === 'sm' ? 32 : 52;
  return (
    <Image
      src="/logo.png"
      alt="AlgoICT"
      width={h}
      height={h}
      className="object-contain"
    />
  );
}
