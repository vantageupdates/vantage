// Pack the approved Image Gen wordmark into an EQ-native, final-size texture.
// No font substitution: the logo comes from the approved artwork. The version
// remains an ordinary XML label so future releases never bake stale digits.
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;

public static class VantageBrandHeader {
    static double Distance(double x, double y, double w, double h, double r, double inset) {
        double qx=Math.Abs(x-w/2)-(w/2-inset-r);
        double qy=Math.Abs(y-h/2)-(h/2-inset-r);
        return Math.Sqrt(Math.Pow(Math.Max(qx,0),2)+Math.Pow(Math.Max(qy,0),2))
            +Math.Min(Math.Max(qx,qy),0)-r;
    }
    static int Coverage(int x,int y,int w,int h,double r,double inset) {
        int count=0;
        for(int sy=0;sy<8;sy++) for(int sx=0;sx<8;sx++)
            if(Distance(x+(sx+.5)/8,y+(sy+.5)/8,w,h,r,inset)<=0) count++;
        return (255*count+32)/64;
    }
    public static void Render(string artwork,string destination,string preview) {
        if(Path.GetFileName(destination)!="VantageBrandHeader.tga")
            throw new ArgumentException("Only the dedicated brand header texture is supported.");
        using(var source=new Bitmap(artwork))
        using(var logo=new Bitmap(94,20,PixelFormat.Format32bppArgb))
        using(var atlas=new Bitmap(256,32,PixelFormat.Format32bppArgb)) {
            if(source.Width!=2167 || source.Height!=725)
                throw new ArgumentException("Expected the approved 2167x725 logo artwork.");
            using(var g=Graphics.FromImage(logo)) {
                g.Clear(Color.FromArgb(16,16,16));
                g.InterpolationMode=InterpolationMode.HighQualityBicubic;
                g.PixelOffsetMode=PixelOffsetMode.HighQuality;
                // The approved wordmark only. Excludes the example v1.44.67 badge.
                g.DrawImage(source,new Rectangle(0,0,94,20),52,218,1420,308,GraphicsUnit.Pixel);
            }
            for(int y=0;y<20;y++) for(int x=0;x<202;x++) {
                int alpha=Coverage(x,y,202,20,5,.25);
                if(alpha==0) continue;
                Color c=Color.FromArgb(16,16,16);
                if(x>=18 && x<112) c=logo.GetPixel(x-18,y);
                // An understated single-line rounded version frame at native size.
                if(x>=124 && x<188 && y>=1 && y<19) {
                    int bx=x-124, by=y-1;
                    int rim=Math.Max(0,Coverage(bx,by,64,18,4,.3)
                        -Coverage(bx,by,64,18,3.3,1));
                    double t=rim/255.0*.72;
                    c=Color.FromArgb((int)Math.Round(16*(1-t)+199*t),
                        (int)Math.Round(16*(1-t)+174*t),(int)Math.Round(16*(1-t)+118*t));
                }
                atlas.SetPixel(x+2,y+2,Color.FromArgb(alpha,c.R,c.G,c.B));
            }
            using(var output=new BinaryWriter(File.Create(destination))) {
                byte[] header=new byte[18]; header[2]=2; header[13]=1;
                header[14]=32; header[16]=32; header[17]=40;
                output.Write(header);
                for(int y=0;y<32;y++) for(int x=0;x<256;x++) {
                    var c=atlas.GetPixel(x,y);
                    output.Write(c.B); output.Write(c.G); output.Write(c.R); output.Write(c.A);
                }
            }
            if(!String.IsNullOrEmpty(preview)) atlas.Save(preview,ImageFormat.Png);
        }
    }
}
